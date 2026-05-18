from __future__ import annotations

import re
import ast
from pathlib import Path
from time import perf_counter

from app.db import save_code_session, save_training_capture
from app.models.schemas import CodeTutorResult, ExecutionResult, ResponseProfile
from app.services.code_runner import ExecutionBackend
from app.services.llm import LLMError, LLMProvider
from app.services.prompts_experimental import (
    EXPERIMENTAL_CODE_TUTOR_PROMPT,
    HYBRID_CODE_TUTOR_PROMPT,
    parse_experimental_code_response,
    parse_hybrid_code_response,
)


CODE_TUTOR_SYSTEM_PROMPT = """
You are AccessLab in beginner_code_tutor mode.

Rules:
- Explain the bug in simple beginner-friendly language.
- Base your reasoning on the runtime or test evidence only.
- Separate the diagnosis from the evidence.
- In the evidence section, quote one or two short concrete lines from the runtime or test output.
- Suggest the smallest next fix.
- Keep the patch minimal.
- Do not rewrite the whole program unless necessary.
- Explain why the final fix works by connecting it back to the evidence.

Return exactly:
<what_failed>What failed here.</what_failed>
<evidence>What evidence shows that, with a short quote.</evidence>
<smallest_next_fix>Your smallest next fix here.</smallest_next_fix>
<patched_code>Your full patched Python code here without markdown fences.</patched_code>
<why_it_works>Your explanation here.</why_it_works>
""".strip()

CODE_TUTOR_SETTINGS = {"temperature": 0.1}


def extract_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def pick_evidence_excerpt(execution_evidence: str) -> str:
    lines = [line.strip() for line in execution_evidence.splitlines() if line.strip()]
    if not lines:
        return "The initial local run did not produce a clear error line."

    priority_terms = ("assert", "error", "exception", "failed", "expected", "returned", "traceback", "nameerror")
    for line in lines:
        normalized = line.lower()
        if any(term in normalized for term in priority_terms):
            return line
    return lines[0]


def parse_code_tutor_response(raw_response: str, original_code: str, execution_evidence: str) -> tuple[str, str, str, str, str]:
    diagnosis = extract_tag(raw_response, "what_failed") or extract_tag(raw_response, "diagnosis")
    evidence = extract_tag(raw_response, "evidence")
    next_fix = extract_tag(raw_response, "smallest_next_fix")
    patched_code = extract_tag(raw_response, "patched_code")
    why_it_works = extract_tag(raw_response, "why_it_works")

    if not patched_code:
        code_fence = re.search(r"```python(.*?)```", raw_response, flags=re.DOTALL | re.IGNORECASE)
        patched_code = code_fence.group(1).strip() if code_fence else original_code

    if not diagnosis:
        diagnosis = "I could not parse a structured explanation of what failed from the local model output."
    if not evidence:
        evidence = f'Initial run evidence: "{pick_evidence_excerpt(execution_evidence)}"'
    if not next_fix:
        next_fix = "Check the failing line and apply the smallest change that matches the error output."
    if not why_it_works:
        why_it_works = "The patch should align the code with the quoted failing test or runtime evidence."

    return diagnosis, evidence, next_fix, patched_code, why_it_works


def _empty_execution_result(status: str, stderr: str) -> ExecutionResult:
    return ExecutionResult(
        status=status,
        return_code=None,
        stdout="",
        stderr=stderr,
        timed_out=False,
        command=[],
        mode=status,
        effective_test_code=None,
        used_generated_tests=False,
    )


def _top_level_definitions(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }


def _submission_import_names(tests: str | None) -> set[str]:
    if not tests or not tests.strip():
        return set()
    try:
        tree = ast.parse(tests)
    except SyntaxError:
        return set()

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "submission":
            imported.update(alias.name for alias in node.names if alias.name != "*")
    return imported


def _missing_submission_imports(code: str, tests: str | None) -> set[str]:
    imported_names = _submission_import_names(tests)
    if not imported_names:
        return set()
    return imported_names - _top_level_definitions(code)


def _serialize_execution_result(result: ExecutionResult) -> dict[str, object]:
    return {
        "status": result.status,
        "return_code": result.return_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": result.timed_out,
        "command": result.command,
        "mode": result.mode,
        "effective_test_code": result.effective_test_code,
        "used_generated_tests": result.used_generated_tests,
        "working_directory": result.working_directory,
        "sandbox_profile": result.sandbox_profile,
        "sandbox_note": result.sandbox_note,
        "denied_by_policy": result.denied_by_policy,
    }


def _serialize_profile(profile: ResponseProfile) -> dict[str, object]:
    return {
        "ttft_seconds": profile.ttft_seconds,
        "prompt_build_seconds": profile.prompt_build_seconds,
        "model_inference_seconds": profile.model_inference_seconds,
        "post_processing_seconds": profile.post_processing_seconds,
        "code_execution_seconds": profile.code_execution_seconds,
        "patched_execution_seconds": profile.patched_execution_seconds,
        "total_seconds": profile.total_seconds,
        "prompt_characters": profile.prompt_characters,
        "context_characters": profile.context_characters,
        "response_characters": profile.response_characters,
        "load_duration_sec": profile.load_duration_sec,
        "prompt_eval_duration_sec": profile.prompt_eval_duration_sec,
        "eval_duration_sec": profile.eval_duration_sec,
        "prompt_eval_count": profile.prompt_eval_count,
        "eval_count": profile.eval_count,
        "queue_wait_seconds": profile.queue_wait_seconds,
        "peak_memory_mb": profile.peak_memory_mb,
    }


def _build_code_session_payload(
    *,
    instruction: str | None,
    original_code: str,
    form_tests: str | None,
    result: CodeTutorResult,
    prompt_variant: str,
    runtime_backend: str,
    model_name: str,
) -> dict[str, object]:
    return {
        "instruction": instruction or "",
        "original_code": original_code,
        "form_tests": form_tests or "",
        "prompt_variant": prompt_variant,
        "runtime_backend": runtime_backend,
        "model_name": model_name,
        "diagnosis": result.diagnosis,
        "evidence": result.evidence,
        "next_fix": result.next_fix,
        "why_it_works": result.why_it_works,
        "patched_code": result.patched_code,
        "result_mode": result.result_mode,
        "initial_run": _serialize_execution_result(result.initial_run),
        "patched_run": _serialize_execution_result(result.patched_run),
        "rerun_success": result.patched_run.passed,
        "profile": _serialize_profile(result.profile or ResponseProfile()),
    }


# Default code-tutor prompt variant. Promoted from "baseline" to "hybrid"
# after the A/B/C benchmark on the 8-task code subset:
#   baseline:     8/8 pass, 8/8 parse, decode 11.35s, 657.8 tokens
#   experimental: 2/8 pass, 6/8 parse, decode  6.79s, 398.5 tokens
#   hybrid:       8/8 pass, 8/8 parse, decode  8.08s, 475.4 tokens
# Hybrid restored 100% pass + parse while keeping ~28% decode/token
# reduction vs baseline. The QA service default is intentionally left
# on "baseline" so this promotion is isolated to the code tutor.
DEFAULT_CODE_TUTOR_PROMPT_VARIANT = "hybrid"


class CodeTutorService:
    def __init__(
        self,
        *,
        db_path: Path,
        llm_provider: LLMProvider,
        execution_backend: ExecutionBackend,
        llm_settings: dict | None = None,
        prompt_variant: str = DEFAULT_CODE_TUTOR_PROMPT_VARIANT,
        training_capture_enabled: bool = False,
    ) -> None:
        self.db_path = db_path
        self.llm_provider = llm_provider
        self.execution_backend = execution_backend
        self.llm_settings = {**CODE_TUTOR_SETTINGS, **(llm_settings or {})}
        self.prompt_variant = prompt_variant
        self.training_capture_enabled = bool(training_capture_enabled)

    def _persist_result(
        self,
        *,
        instruction: str | None,
        original_code: str,
        form_tests: str | None,
        execution_output: str,
        patched_test_result: str,
        result: CodeTutorResult,
        actor_role: str,
        actor_key: str,
        class_space: str,
    ) -> int:
        runtime_backend = getattr(self.llm_provider, "backend_name", "ollama")
        model_name = getattr(self.llm_provider, "model_name", "")
        session_payload = _build_code_session_payload(
            instruction=instruction,
            original_code=original_code,
            form_tests=form_tests,
            result=result,
            prompt_variant=self.prompt_variant,
            runtime_backend=runtime_backend,
            model_name=model_name,
        )
        session_id = save_code_session(
            self.db_path,
            original_code=original_code,
            test_code=form_tests,
            execution_output=execution_output,
            patched_code=result.patched_code,
            patched_test_result=patched_test_result,
            actor_role=actor_role,
            actor_key=actor_key,
            class_space=class_space,
            session_data=session_payload,
        )
        if self.training_capture_enabled:
            capture_payload = {
                **session_payload,
                "capture_version": "v1",
                "repair_style_role": actor_role,
                "sandbox_blocked": result.result_mode == "blocked",
            }
            save_training_capture(
                self.db_path,
                source_type="code",
                source_id=session_id,
                capture_kind="code-repair",
                actor_role=actor_role,
                actor_key=actor_key,
                class_space=class_space,
                retrieval_mode="",
                weak_retrieval=False,
                runtime_backend=runtime_backend,
                model_name=model_name,
                prompt_variant=self.prompt_variant,
                payload=capture_payload,
            )
        return session_id

    def tutor(
        self,
        code: str,
        tests: str | None = None,
        instruction: str | None = None,
        *,
        actor_role: str = "learner",
        actor_key: str = "local-user",
        class_space: str = "default-classroom",
        queue_wait_seconds: float = 0.0,
    ) -> CodeTutorResult:
        total_start = perf_counter()
        profile = ResponseProfile()
        profile.queue_wait_seconds = round(float(queue_wait_seconds or 0.0), 3)

        missing_test_imports = _missing_submission_imports(code, tests)
        if missing_test_imports:
            missing_label = ", ".join(sorted(missing_test_imports))
            message = (
                f"The tests import {missing_label} from submission.py, but this code does not define "
                f"{missing_label}."
            )
            initial_run = ExecutionResult(
                status="not_run",
                return_code=None,
                stdout="",
                stderr=message,
                timed_out=False,
                command=[],
                mode="test_mismatch",
                effective_test_code=tests,
                used_generated_tests=False,
                sandbox_profile=getattr(self.execution_backend, "sandbox_profile", "none"),
                sandbox_note=getattr(self.execution_backend, "sandbox_note", ""),
            )
            patched_run = _empty_execution_result("not_run", "No rerun was attempted because the tests do not match the submitted code.")
            result = CodeTutorResult(
                diagnosis="The tests do not match this code.",
                evidence=message,
                next_fix="Clear the optional tests, or change them so they import names that this code actually defines.",
                patched_code=code,
                why_it_works="This prevents the assistant from repairing your code toward an unrelated sample function.",
                initial_run=initial_run,
                patched_run=patched_run,
                result_mode="test_mismatch",
                profile=profile,
            )
            profile.total_seconds = perf_counter() - total_start
            result.session_id = self._persist_result(
                instruction=instruction,
                original_code=code,
                form_tests=tests,
                execution_output=initial_run.stderr,
                patched_test_result=patched_run.stderr,
                result=result,
                actor_role=actor_role,
                actor_key=actor_key,
                class_space=class_space,
            )
            return result

        execution_start = perf_counter()
        initial_run = self.execution_backend.run(code, tests)
        profile.code_execution_seconds = perf_counter() - execution_start

        if initial_run.status == "blocked":
            patched_run = _empty_execution_result("not_run", "No rerun was attempted because the submission was blocked.")
            result = CodeTutorResult(
                diagnosis="The local runner blocked this code because it crossed the demo sandbox policy.",
                evidence="The blocked runner did not complete the submission, so no normal runtime evidence is available.",
                next_fix="Remove restricted imports or retry without network access, child processes, or filesystem writes outside the temporary run directory.",
                patched_code=code,
                why_it_works="This prototype supports a narrow beginner-Python subset and now denies higher-risk local operations more explicitly.",
                initial_run=initial_run,
                patched_run=patched_run,
                result_mode="blocked",
                profile=profile,
            )
            profile.total_seconds = perf_counter() - total_start
            result.session_id = self._persist_result(
                instruction=instruction,
                original_code=code,
                form_tests=tests,
                execution_output=initial_run.combined_output or initial_run.stderr,
                patched_test_result=patched_run.stderr,
                result=result,
                actor_role=actor_role,
                actor_key=actor_key,
                class_space=class_space,
            )
            return result

        health_ok, health_message = self.llm_provider.health_check()
        if not health_ok:
            patched_run = _empty_execution_result("not_run", "No rerun was attempted because the local model was unavailable.")
            result = CodeTutorResult(
                diagnosis="The code ran, but the configured Gemma 4 model is not ready to explain the bug.",
                evidence=f'Initial run evidence: "{pick_evidence_excerpt(initial_run.combined_output or "No output.")}"',
                next_fix=health_message,
                patched_code=code,
                why_it_works="Start Ollama, install the configured Gemma 4 model, and try the code tutor flow again.",
                initial_run=initial_run,
                patched_run=patched_run,
                result_mode="model_unavailable",
                profile=profile,
            )
            profile.total_seconds = perf_counter() - total_start
            result.session_id = self._persist_result(
                instruction=instruction,
                original_code=code,
                form_tests=initial_run.effective_test_code or tests,
                execution_output=initial_run.combined_output or "No output.",
                patched_test_result=patched_run.stderr,
                result=result,
                actor_role=actor_role,
                actor_key=actor_key,
                class_space=class_space,
            )
            return result

        prompt_build_start = perf_counter()
        if self.prompt_variant == "experimental":
            system_prompt = EXPERIMENTAL_CODE_TUTOR_PROMPT
        elif self.prompt_variant == "hybrid":
            system_prompt = HYBRID_CODE_TUTOR_PROMPT
        else:
            system_prompt = CODE_TUTOR_SYSTEM_PROMPT
        prompt_parts = [system_prompt, ""]
        if instruction and instruction.strip():
            prompt_parts.extend(["User request:", instruction.strip(), ""])
        prompt_parts.extend(
            [
                "Original code:",
                code,
                "",
                "Tests or harness:",
                initial_run.effective_test_code or "No tests were provided.",
                "",
                "Execution evidence:",
                initial_run.combined_output or "The program produced no output.",
            ]
        )
        prompt = "\n".join(prompt_parts)
        context = "Patch only the code that is necessary to fix the beginner-level problem."
        profile.prompt_build_seconds = perf_counter() - prompt_build_start
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
            raw_response = (
                "<what_failed>The configured Gemma 4 model could not be reached.</what_failed>"
                f'<evidence>Initial run evidence: "{pick_evidence_excerpt(initial_run.combined_output or "No output.")}"</evidence>'
                f"<smallest_next_fix>{exc}</smallest_next_fix>"
                f"<patched_code>{code}</patched_code>"
                "<why_it_works>Once the configured Gemma 4 model is available, AccessLab can propose a minimal patch.</why_it_works>"
            )

        post_processing_start = perf_counter()
        execution_evidence = initial_run.combined_output or "No output."
        if self.prompt_variant == "experimental":
            diagnosis, evidence, next_fix, patched_code, why_it_works = parse_experimental_code_response(
                raw_response, code, execution_evidence
            )
        elif self.prompt_variant == "hybrid":
            diagnosis, evidence, next_fix, patched_code, why_it_works = parse_hybrid_code_response(
                raw_response, code, execution_evidence
            )
        else:
            diagnosis, evidence, next_fix, patched_code, why_it_works = parse_code_tutor_response(
                raw_response, code, execution_evidence
            )
        profile.post_processing_seconds = perf_counter() - post_processing_start
        profile.response_characters = len(raw_response)

        patched_execution_start = perf_counter()
        patched_run = self.execution_backend.run(patched_code, initial_run.effective_test_code or tests)
        profile.patched_execution_seconds = perf_counter() - patched_execution_start

        result = CodeTutorResult(
            diagnosis=diagnosis,
            evidence=evidence,
            next_fix=next_fix,
            patched_code=patched_code,
            why_it_works=why_it_works,
            initial_run=initial_run,
            patched_run=patched_run,
            result_mode="completed",
            raw_response=raw_response,
            profile=profile,
        )
        profile.total_seconds = perf_counter() - total_start
        result.session_id = self._persist_result(
            instruction=instruction,
            original_code=code,
            form_tests=initial_run.effective_test_code or tests,
            execution_output=initial_run.combined_output or "No output.",
            patched_test_result=patched_run.combined_output or patched_run.stderr or patched_run.status,
            result=result,
            actor_role=actor_role,
            actor_key=actor_key,
            class_space=class_space,
        )
        return result
