from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from app.db import save_qa_history, save_training_capture
from app.models.schemas import Citation, QAResult, ResponseProfile, SearchResult
from app.services.llm import LLMError, LLMProvider
from app.services.prompts_experimental import (
    EXPERIMENTAL_QA_SYSTEM_PROMPT,
    parse_experimental_qa_response,
)
from app.services.retrieval import RetrievalBackend, is_weak_retrieval


GROUNDED_QA_SYSTEM_PROMPT = """
You are AccessLab in grounded_qa mode.

Rules:
- Answer only from the retrieved material.
- If the material is weak or incomplete, say you are unsure.
- Use simple language for a beginner.
- Keep the answer concise.
- Follow the user's requested structure when possible, such as short numbered steps or quoted snippets.
- If the user asks for a quote, include a short quote from a cited source.
- If the user asks for screen-reader-friendly output or short paragraphs, keep each paragraph under two sentences.
- Use plain text only inside the answer content. Do not use markdown emphasis, markdown headings, or tables.
- Cite source labels like [S1].
- Do not invent facts beyond the context.

Return exactly:
<short_answer>Your short answer here.</short_answer>
<more_detail>Your optional extra detail here. Leave empty if you do not need it.</more_detail>
""".strip()

GROUNDED_QA_SETTINGS = {"temperature": 0.2}

ANSWER_LANGUAGE_LABELS = {
    "auto": "Match question",
    "english": "English",
    "spanish": "Spanish",
    "french": "French",
    "swahili": "Swahili",
    "hindi": "Hindi",
    "arabic": "Arabic",
}


# Weak-tier QA output-discipline suffix. Appended to GROUNDED_QA_SYSTEM_PROMPT
# only when qa_discipline_profile == "weak" (see GroundedQAService below).
#
# Purpose. The model-tier sweep on 2026-04-19 (see
# reports/model_tier_decision_memo.md) showed that under constrained-proxy
# stress the small `gemma4:e2b` model keeps parse reliability at 20/20 and
# code at 8/8 but loses 2/4 on the accessibility/output-format subset. Both
# misses had correct content; both were flagged as "too verbose" by the
# evaluator:
#   - a11y-01: <more_detail> ballooned with multi-sentence bullets and the
#     total word count went above the 120-word budget.
#   - a11y-02: the model produced a 2-sentence <short_answer> followed by a
#     trailing "[S1] [S2]" citation cluster. The evaluator's sentence
#     splitter (re.split(r"(?<=[.!?])\s+", text)) treats the trailing
#     bracketed cluster as a third sentence, tripping the
#     "every paragraph ≤ 2 sentences" check.
#
# This suffix targets exactly those two failure modes without changing
# retrieval, the parse contract, or the grounding rules. It is intentionally
# narrow: it does not give the model anything new to say, it forces it to
# say less, more predictably.
WEAK_TIER_QA_DISCIPLINE_SUFFIX = """

Output discipline (this device runs a small model; brevity is required):
- Keep <short_answer> to ONE simple sentence.
- Place every citation inside the sentence it supports, before the final
  period. For example: "...goes through the list one item at a time [S1]."
- Do NOT add a separate trailing line of citation tags after the sentence.
- Keep <more_detail> to AT MOST two short sentences in ONE paragraph. Leave
  it empty if <short_answer> already answers the question.
- Do NOT add bullet lists, numbered steps, headings, or extra examples.
- Prefer the shortest correct answer. Stop as soon as the question is
  answered.
""".rstrip()


# Default QA prompt variant. Intentionally pinned to "baseline" after the
# full-pack model-tier sweep on 2026-04-19 (see
# reports/model_tier_decision_memo.md). The baseline XML-tag prompt is the
# variant that has been validated end-to-end for grounded QA: it scored
# 20/20 / 20/20 on the warm e4b reference run with no regressions across
# any worksheet/local-doc task.
#
# The "experimental" variant trades parse reliability for shorter prompts
# and is *not* a safe QA default. The "hybrid" variant exists only for the
# code-tutor path (see DEFAULT_CODE_TUTOR_PROMPT_VARIANT in
# app/services/code_tutor.py); it does not change QA behaviour but is left
# selectable so QA-side regressions can still be benchmarked.
DEFAULT_QA_PROMPT_VARIANT = "baseline"


# QA output-discipline profile. Controls whether the weak-tier discipline
# suffix is appended to the baseline QA system prompt.
#   "default" -> use GROUNDED_QA_SYSTEM_PROMPT as-is (strong-tier behavior).
#   "weak"    -> append WEAK_TIER_QA_DISCIPLINE_SUFFIX to enforce stricter
#                output-length and inline-citation rules. Only meaningful
#                with prompt_variant == "baseline"; ignored otherwise so the
#                experimental QA variant remains a clean prefill A/B target.
KNOWN_QA_DISCIPLINE_PROFILES = ("default", "weak")
DEFAULT_QA_DISCIPLINE_PROFILE = "default"


def truncate_snippet(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def build_citations(results: list[SearchResult]) -> list[Citation]:
    citations: list[Citation] = []
    for index, result in enumerate(results, start=1):
        citations.append(
            Citation(
                label=f"S{index}",
                source_file=result.source_file,
                page_number=result.page_number,
                chunk_id=result.chunk_id,
                snippet=truncate_snippet(result.chunk_text),
            )
        )
    return citations


def _extract_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def serialize_citations(citations: list[Citation]) -> list[dict[str, object]]:
    return [asdict(citation) for citation in citations]


def serialize_search_results(results: list[SearchResult]) -> list[dict[str, object]]:
    return [
        {
            "chunk_id": result.chunk_id,
            "source_file": result.source_file,
            "page_number": result.page_number,
            "chunk_text": result.chunk_text,
            "snippet": result.snippet,
            "score": result.score,
            "match_source": result.match_source,
            "semantic_similarity": result.semantic_similarity,
        }
        for result in results
    ]


def _build_profile_payload(profile: ResponseProfile) -> dict[str, object]:
    return {
        "ttft_seconds": profile.ttft_seconds,
        "retrieval_seconds": profile.retrieval_seconds,
        "prompt_build_seconds": profile.prompt_build_seconds,
        "model_inference_seconds": profile.model_inference_seconds,
        "post_processing_seconds": profile.post_processing_seconds,
        "total_seconds": profile.total_seconds,
        "prompt_characters": profile.prompt_characters,
        "context_characters": profile.context_characters,
        "response_characters": profile.response_characters,
        "retrieved_chunks": profile.retrieved_chunks,
        "load_duration_sec": profile.load_duration_sec,
        "prompt_eval_duration_sec": profile.prompt_eval_duration_sec,
        "eval_duration_sec": profile.eval_duration_sec,
        "prompt_eval_count": profile.prompt_eval_count,
        "eval_count": profile.eval_count,
        "retrieval_mode": profile.retrieval_mode,
        "retrieval_mode_label": profile.retrieval_mode_label,
        "semantic_status_code": profile.semantic_status_code,
        "semantic_index_status": profile.semantic_index_status,
        "queue_wait_seconds": profile.queue_wait_seconds,
        "peak_memory_mb": profile.peak_memory_mb,
    }


def _build_qa_session_payload(
    *,
    question: str,
    result: QAResult,
    raw_response: str,
    results: list[SearchResult],
    prompt_variant: str,
    qa_discipline_profile: str,
    runtime_backend: str,
    model_name: str,
    answer_language: str,
    answer_language_label: str,
    plain_language_requested: bool,
) -> dict[str, object]:
    return {
        "question": question,
        "answer_language": answer_language,
        "answer_language_label": answer_language_label,
        "plain_language_requested": plain_language_requested,
        "short_answer": result.short_answer,
        "more_detail": result.more_detail,
        "unsure": result.unsure,
        "result_mode": result.result_mode,
        "prompt_variant": prompt_variant,
        "qa_discipline_profile": qa_discipline_profile,
        "runtime_backend": runtime_backend,
        "model_name": model_name,
        "raw_response": raw_response,
        "citations": serialize_citations(result.citations),
        "retrieved_results": serialize_search_results(results),
        "profile": _build_profile_payload(result.profile or ResponseProfile()),
    }


def parse_qa_response(raw_response: str, citations: list[Citation]) -> tuple[str, str]:
    short_answer = _extract_tag(raw_response, "short_answer")
    more_detail = _extract_tag(raw_response, "more_detail")

    if not short_answer:
        paragraphs = [part.strip() for part in raw_response.split("\n") if part.strip()]
        short_answer = paragraphs[0] if paragraphs else "I could not create a grounded answer from the local material."
        more_detail = "\n".join(paragraphs[1:])

    if citations and not re.search(r"\[S\d+(?:\s*,\s*S\d+)*\]", short_answer):
        refs = " ".join(f"[{citation.label}]" for citation in citations[:2])
        short_answer = f"{short_answer} {refs}".strip()

    return short_answer, more_detail


def enforce_accessible_layout(question: str, short_answer: str, more_detail: str) -> tuple[str, str]:
    lowered = question.lower()
    if "screen-reader-friendly" not in lowered and "paragraph under 2 sentences" not in lowered and "keep every paragraph under 2 sentences" not in lowered:
        return short_answer, more_detail

    short_answer = re.sub(r"^\s*1\.\s*short answer:\s*", "", short_answer, flags=re.IGNORECASE)
    more_detail = re.sub(r"^\s*2\.\s*explanation:\s*", "", more_detail, flags=re.IGNORECASE)
    more_detail = re.sub(r"\s*3\.\s*sources:.*$", "", more_detail, flags=re.IGNORECASE | re.DOTALL)

    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", more_detail.strip()) if sentence.strip()]
    if not sentences:
        return short_answer.strip(), ""

    paragraphs: list[str] = []
    for index in range(0, len(sentences), 2):
        paragraphs.append(" ".join(sentences[index : index + 2]))

    return short_answer.strip(), "\n".join(paragraphs)


def detect_uncertainty(short_answer: str, more_detail: str) -> bool:
    combined = f"{short_answer}\n{more_detail}".lower()
    markers = (
        "i am unsure",
        "i'm unsure",
        "i am not sure",
        "i am not fully sure",
        "could not find a close match",
    )
    return any(marker in combined for marker in markers)


def normalize_answer_language(answer_language: str | None) -> str:
    normalized = (answer_language or "auto").strip().lower()
    if normalized not in ANSWER_LANGUAGE_LABELS:
        return "auto"
    return normalized


def answer_language_label(answer_language: str | None) -> str:
    return ANSWER_LANGUAGE_LABELS[normalize_answer_language(answer_language)]


def build_answer_guidance(
    *,
    answer_language: str | None = "auto",
    plain_language_requested: bool = False,
) -> str:
    guidance: list[str] = []
    normalized_language = normalize_answer_language(answer_language)
    if normalized_language != "auto":
        guidance.append(
            f"Answer in {ANSWER_LANGUAGE_LABELS[normalized_language]} while citing the local classroom sources."
        )
    if plain_language_requested:
        guidance.append(
            "Use plain, simple language suitable for a beginner student."
        )
    if not guidance:
        return ""
    return "Answer guidance:\n" + "\n".join(f"- {item}" for item in guidance)


class GroundedQAService:
    def __init__(
        self,
        *,
        db_path: Path,
        retrieval_backend: RetrievalBackend,
        llm_provider: LLMProvider,
        llm_settings: dict | None = None,
        prompt_variant: str = DEFAULT_QA_PROMPT_VARIANT,
        qa_discipline_profile: str = DEFAULT_QA_DISCIPLINE_PROFILE,
        training_capture_enabled: bool = False,
    ) -> None:
        self.db_path = db_path
        self.retrieval_backend = retrieval_backend
        self.llm_provider = llm_provider
        self.llm_settings = {**GROUNDED_QA_SETTINGS, **(llm_settings or {})}
        self.prompt_variant = prompt_variant
        self.training_capture_enabled = bool(training_capture_enabled)
        normalized_discipline = (qa_discipline_profile or DEFAULT_QA_DISCIPLINE_PROFILE).strip().lower()
        if normalized_discipline not in KNOWN_QA_DISCIPLINE_PROFILES:
            normalized_discipline = DEFAULT_QA_DISCIPLINE_PROFILE
        self.qa_discipline_profile = normalized_discipline

    def _resolve_system_prompt(self) -> str:
        """Return the active QA system prompt for this service instance.

        The weak-tier discipline suffix only attaches to the baseline prompt;
        the experimental variant intentionally stays minimal so it remains a
        clean prefill A/B target.
        """
        if self.prompt_variant == "experimental":
            return EXPERIMENTAL_QA_SYSTEM_PROMPT
        if self.qa_discipline_profile == "weak":
            return GROUNDED_QA_SYSTEM_PROMPT + "\n" + WEAK_TIER_QA_DISCIPLINE_SUFFIX
        return GROUNDED_QA_SYSTEM_PROMPT

    def _persist_answer(
        self,
        *,
        question: str,
        answer: QAResult,
        raw_response: str,
        results: list[SearchResult],
        actor_role: str,
        actor_key: str,
        class_space: str,
        retrieval_mode: str,
        retrieval_mode_label: str,
        answer_language: str,
        plain_language_requested: bool,
    ) -> int:
        runtime_backend = getattr(self.llm_provider, "backend_name", "ollama")
        model_name = getattr(self.llm_provider, "model_name", "")
        normalized_language = normalize_answer_language(answer_language)
        session_payload = _build_qa_session_payload(
            question=question,
            result=answer,
            raw_response=raw_response,
            results=results,
            prompt_variant=self.prompt_variant,
            qa_discipline_profile=self.qa_discipline_profile,
            runtime_backend=runtime_backend,
            model_name=model_name,
            answer_language=normalized_language,
            answer_language_label=answer_language_label(normalized_language),
            plain_language_requested=bool(plain_language_requested),
        )
        history_id = save_qa_history(
            self.db_path,
            question=question,
            retrieved_chunk_ids=[result.chunk_id for result in results],
            answer_text=answer.short_answer,
            more_detail=answer.more_detail,
            unsure=answer.unsure,
            result_mode=answer.result_mode,
            actor_role=actor_role,
            actor_key=actor_key,
            class_space=class_space,
            retrieval_mode=retrieval_mode,
            retrieval_mode_label=retrieval_mode_label,
            citation_list=serialize_citations(answer.citations),
            session_data=session_payload,
        )
        if self.training_capture_enabled:
            capture_payload = {
                **session_payload,
                "capture_version": "v1",
                "answer_style_role": actor_role,
                "weak_retrieval": answer.result_mode == "weak_match",
                "screen_reader_format_requested": "screen-reader-friendly" in question.lower(),
                "over_disclosure_flagged": False,
            }
            save_training_capture(
                self.db_path,
                source_type="qa",
                source_id=history_id,
                capture_kind="grounded-qa",
                actor_role=actor_role,
                actor_key=actor_key,
                class_space=class_space,
                retrieval_mode=retrieval_mode,
                weak_retrieval=answer.result_mode == "weak_match",
                runtime_backend=runtime_backend,
                model_name=model_name,
                prompt_variant=self.prompt_variant,
                payload=capture_payload,
            )
        return history_id

    def answer(
        self,
        question: str,
        *,
        actor_role: str = "learner",
        actor_key: str = "local-user",
        class_space: str = "default-classroom",
        queue_wait_seconds: float = 0.0,
        answer_language: str = "auto",
        plain_language_requested: bool = False,
    ) -> QAResult:
        clean_question = question.strip()
        normalized_language = normalize_answer_language(answer_language)
        total_start = perf_counter()
        profile = ResponseProfile()
        profile.queue_wait_seconds = round(float(queue_wait_seconds or 0.0), 3)

        retrieval_start = perf_counter()
        results = self.retrieval_backend.search(clean_question, limit=4)
        profile.retrieval_seconds = perf_counter() - retrieval_start
        profile.retrieved_chunks = len(results)
        retrieval_mode, retrieval_mode_label = self.retrieval_backend.current_mode()
        profile.retrieval_mode = retrieval_mode
        profile.retrieval_mode_label = retrieval_mode_label

        prompt_build_start = perf_counter()
        citations = build_citations(results)
        profile.prompt_build_seconds = perf_counter() - prompt_build_start

        if not results:
            answer = QAResult(
                question=clean_question,
                short_answer="I could not find a close match in the uploaded materials.",
                more_detail="Try a more specific question or upload the worksheet page that contains the answer.",
                citations=[],
                unsure=True,
                result_mode="no_match",
                profile=profile,
                retrieval_mode=retrieval_mode,
                retrieval_mode_label=retrieval_mode_label,
            )
            profile.total_seconds = perf_counter() - total_start
            answer.history_id = self._persist_answer(
                question=clean_question,
                answer=answer,
                raw_response="",
                results=[],
                actor_role=actor_role,
                actor_key=actor_key,
                class_space=class_space,
                retrieval_mode=retrieval_mode,
                retrieval_mode_label=retrieval_mode_label,
                answer_language=normalized_language,
                plain_language_requested=plain_language_requested,
            )
            return answer

        if is_weak_retrieval(clean_question, results):
            answer = QAResult(
                question=clean_question,
                short_answer="I am not fully sure. These are the closest matching local snippets instead of a guessed answer.",
                more_detail="The retrieval match is weak, so AccessLab is showing sources rather than hallucinating.",
                citations=citations,
                unsure=True,
                result_mode="weak_match",
                profile=profile,
                retrieval_mode=retrieval_mode,
                retrieval_mode_label=retrieval_mode_label,
            )
            profile.total_seconds = perf_counter() - total_start
            answer.history_id = self._persist_answer(
                question=clean_question,
                answer=answer,
                raw_response="",
                results=results,
                actor_role=actor_role,
                actor_key=actor_key,
                class_space=class_space,
                retrieval_mode=retrieval_mode,
                retrieval_mode_label=retrieval_mode_label,
                answer_language=normalized_language,
                plain_language_requested=plain_language_requested,
            )
            return answer

        health_ok, health_message = self.llm_provider.health_check()
        if not health_ok:
            answer = QAResult(
                question=clean_question,
                short_answer="I found matching material, but the configured Gemma 4 model is not ready.",
                more_detail=health_message,
                citations=citations,
                unsure=True,
                result_mode="model_unavailable",
                profile=profile,
                retrieval_mode=retrieval_mode,
                retrieval_mode_label=retrieval_mode_label,
            )
            profile.total_seconds = perf_counter() - total_start
            answer.history_id = self._persist_answer(
                question=clean_question,
                answer=answer,
                raw_response="",
                results=results,
                actor_role=actor_role,
                actor_key=actor_key,
                class_space=class_space,
                retrieval_mode=retrieval_mode,
                retrieval_mode_label=retrieval_mode_label,
                answer_language=normalized_language,
                plain_language_requested=plain_language_requested,
            )
            return answer

        prompt_build_start = perf_counter()
        context_parts: list[str] = []
        for citation, result in zip(citations, results, strict=False):
            location = f"{citation.source_file}, page {citation.page_number}" if citation.page_number else citation.source_file
            context_parts.append(
                f"[{citation.label}] {location} | chunk {citation.chunk_id}\n{result.chunk_text}"
            )
        context = "\n\n".join(context_parts)

        system_prompt = self._resolve_system_prompt()
        answer_guidance = build_answer_guidance(
            answer_language=normalized_language,
            plain_language_requested=plain_language_requested,
        )
        prompt = (
            f"{system_prompt}\n\n"
            f"Question: {clean_question}\n"
            "Use the source labels exactly as provided."
        )
        if answer_guidance:
            prompt = f"{prompt}\n\n{answer_guidance}"
        profile.prompt_build_seconds += perf_counter() - prompt_build_start
        profile.prompt_characters = len(prompt)
        profile.context_characters = len(context)

        try:
            inference_start = perf_counter()
            if hasattr(self.llm_provider, "measure_answer"):
                generation = self.llm_provider.measure_answer(
                    prompt,
                    context,
                    settings=self.llm_settings,
                )
                raw_response = generation.text
                profile.ttft_seconds = generation.ttft_seconds
                profile.model_inference_seconds = generation.total_seconds
                profile.load_duration_sec = generation.load_duration_sec
                profile.prompt_eval_duration_sec = generation.prompt_eval_duration_sec
                profile.eval_duration_sec = generation.eval_duration_sec
                profile.prompt_eval_count = generation.prompt_eval_count
                profile.eval_count = generation.eval_count
            else:
                raw_response = self.llm_provider.generate_answer(
                    prompt,
                    context,
                    settings=self.llm_settings,
                )
                profile.model_inference_seconds = perf_counter() - inference_start
        except LLMError as exc:
            raw_response = f"<short_answer>I found matching material, but I could not reach the configured Gemma 4 model. [S1]</short_answer><more_detail>{exc}</more_detail>"

        post_processing_start = perf_counter()
        if self.prompt_variant == "experimental":
            short_answer, more_detail = parse_experimental_qa_response(raw_response)
            # Append citations if they are missing from the model output
            if citations and not re.search(r"\[S\d+(?:\s*,\s*S\d+)*\]", short_answer):
                refs = " ".join(f"[{citation.label}]" for citation in citations[:2])
                short_answer = f"{short_answer} {refs}".strip()
        else:
            short_answer, more_detail = parse_qa_response(raw_response, citations)
        short_answer, more_detail = enforce_accessible_layout(clean_question, short_answer, more_detail)
        unsure = detect_uncertainty(short_answer, more_detail)
        profile.post_processing_seconds = perf_counter() - post_processing_start
        profile.response_characters = len(raw_response)
        answer = QAResult(
            question=clean_question,
            short_answer=short_answer,
            more_detail=more_detail,
            citations=citations,
            unsure=unsure,
            result_mode="answered",
            raw_response=raw_response,
            profile=profile,
            retrieval_mode=retrieval_mode,
            retrieval_mode_label=retrieval_mode_label,
        )
        profile.semantic_status_code = ""
        profile.semantic_index_status = ""
        profile.total_seconds = perf_counter() - total_start
        answer.history_id = self._persist_answer(
            question=clean_question,
            answer=answer,
            raw_response=raw_response,
            results=results,
            actor_role=actor_role,
            actor_key=actor_key,
            class_space=class_space,
            retrieval_mode=retrieval_mode,
            retrieval_mode_label=retrieval_mode_label,
            answer_language=normalized_language,
            plain_language_requested=plain_language_requested,
        )
        return answer
