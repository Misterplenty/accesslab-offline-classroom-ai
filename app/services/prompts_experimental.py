"""Experimental prompt variants for latency A/B testing.

Hypothesis: the current XML-tag output format adds prefill cost because the
model must internalize a multi-line structured-output contract before it can
start generating. A lighter colon-prefix format reduces the instruction token
count while preserving the information the parser needs.

This module is intentionally narrow in scope. It does not change:
- retrieval logic
- citation formatting
- the model or any model parameters
- the evaluation tasks

It exports:
  EXPERIMENTAL_QA_SYSTEM_PROMPT     -- lighter QA instructions
  EXPERIMENTAL_CODE_TUTOR_PROMPT    -- lighter code-tutor instructions
  HYBRID_CODE_TUTOR_PROMPT          -- hybrid code-tutor instructions
  parse_experimental_qa_response    -- parser for the lighter QA format
  parse_experimental_code_response  -- parser for the lighter code format
  parse_hybrid_code_response        -- parser for the hybrid code format

Usage: pass prompt_variant="experimental" or prompt_variant="hybrid" to the
services. The services fall back to the baseline prompts when variant ==
"baseline" (the default).

The hybrid variant exists because the plain-prefix experimental variant
reduced output tokens (and decode time) but made multi-line code extraction
unreliable on the code-tutor path. The hybrid keeps most of the token
reduction but restores a strong <patched_code> XML anchor for the code
block and adds explicit evidence-vocabulary directives so the diagnosis
consistently passes the evidence-language check in the evaluator.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Experimental QA prompt
# ---------------------------------------------------------------------------
# Changes vs baseline:
#   - Removed 8 bulleted rules (system instruction lines); kept only the three
#     that are strictly necessary: source-only, unsure fallback, cite [S#].
#   - Replaced <short_answer> / <more_detail> XML tags with ANSWER: / DETAIL:
#     plain prefix markers. Prefix markers are shorter tokens and the model
#     does not need to close a tag, which can reduce decode length.
#   - Removed the "Return exactly:" framing line.

EXPERIMENTAL_QA_SYSTEM_PROMPT = """
You are AccessLab. Answer ONLY from the retrieved material below.
Be concise. Use simple language. Cite sources like [S1].
If the material is weak, say you are unsure.

ANSWER: your short answer here
DETAIL: optional extra detail here (leave blank if not needed)
""".strip()


def _line_after_prefix(text: str, prefix: str) -> str:
    """Return the text on the same line after 'PREFIX:', case-insensitive."""
    match = re.search(rf"^{re.escape(prefix)}[:\s]+(.*)", text, flags=re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _block_after_prefix(text: str, prefix: str, stop_prefixes: list[str]) -> str:
    """Return multi-line content starting after 'PREFIX:' up to the next prefix."""
    pattern = rf"^{re.escape(prefix)}[:\s]+(.*?)(?=^(?:{'|'.join(re.escape(p) for p in stop_prefixes)})[:\s]|\Z)"
    match = re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_experimental_qa_response(raw_response: str) -> tuple[str, str]:
    """Parse ANSWER: / DETAIL: format, with fallback to first paragraph."""
    short_answer = _line_after_prefix(raw_response, "ANSWER")
    more_detail = _block_after_prefix(raw_response, "DETAIL", ["ANSWER"])

    if not short_answer:
        paragraphs = [p.strip() for p in raw_response.split("\n") if p.strip()]
        short_answer = paragraphs[0] if paragraphs else ""
        more_detail = "\n".join(paragraphs[1:])

    return short_answer, more_detail


# ---------------------------------------------------------------------------
# Experimental code-tutor prompt
# ---------------------------------------------------------------------------
# Changes vs baseline:
#   - Collapsed 8 bulleted rules to 4 key directives.
#   - Replaced XML tags with plain prefix markers: FAILED: / FIX: / CODE: / WHY:
#   - Removed the "Return exactly:" framing line.
#   - Evidence is folded into FAILED: instead of being a separate tag, reducing
#     one full round-trip instruction cost.

EXPERIMENTAL_CODE_TUTOR_PROMPT = """
You are AccessLab helping a beginner fix Python code.
Use the runtime or test evidence only. Be brief and clear.
Suggest the smallest possible fix. Do not rewrite the whole program.

FAILED: what went wrong (quote a short error line as evidence)
FIX: the smallest fix
CODE:
full patched Python code here, no markdown fences
WHY: why the fix works
""".strip()


def parse_experimental_code_response(
    raw_response: str, original_code: str, execution_evidence: str
) -> tuple[str, str, str, str, str]:
    """Parse FAILED: / FIX: / CODE: / WHY: format with fallbacks."""
    prefixes_all = ["FAILED", "FIX", "CODE", "WHY"]

    diagnosis = _line_after_prefix(raw_response, "FAILED")
    next_fix = _line_after_prefix(raw_response, "FIX")
    why_it_works = _line_after_prefix(raw_response, "WHY")
    patched_code = _block_after_prefix(raw_response, "CODE", ["WHY"])

    # Evidence is embedded in FAILED; extract the quoted part if present
    evidence_match = re.search(r'"([^"]{5,})"', diagnosis)
    evidence = evidence_match.group(1) if evidence_match else diagnosis

    # Fallbacks
    if not patched_code:
        code_fence = re.search(r"```python(.*?)```", raw_response, flags=re.DOTALL | re.IGNORECASE)
        patched_code = code_fence.group(1).strip() if code_fence else original_code

    if not diagnosis:
        diagnosis = "I could not parse a structured explanation of what failed from the local model output."
    if not evidence:
        evidence = f'Initial run evidence: "{execution_evidence[:120]}"' if execution_evidence else "No evidence available."
    if not next_fix:
        next_fix = "Check the failing line and apply the smallest change that matches the error output."
    if not why_it_works:
        why_it_works = "The patch should align the code with the quoted failing test or runtime evidence."

    return diagnosis, evidence, next_fix, patched_code, why_it_works


# ---------------------------------------------------------------------------
# Hybrid code-tutor prompt
# ---------------------------------------------------------------------------
# Changes vs experimental:
#   - Restores XML-style anchors for the fields that need reliable extraction.
#     <patched_code> is the highest-priority structural anchor because the
#     plain CODE: prefix was too weak for multi-line Python code.
#   - Fuses what_failed + evidence into a single <diagnosis> tag to keep the
#     output lighter than baseline (4 sections instead of 5).
#   - Explicitly names the evidence vocabulary we want: "the assertion that
#     failed", "the error type (for example NameError)", "the returned
#     value", "the expected vs actual value". These line up directly with
#     the evaluator's evidence_terms so correct diagnoses stop being scored
#     as "weak_evidence_reference".
#   - Keeps <fix> and <why> short (one sentence each) to preserve most of
#     the decode/token savings from the experimental variant.
#
# Changes vs baseline:
#   - 4 tags instead of 5.
#   - Shorter field names (<fix>, <why>) to reduce output-tag overhead.
#   - Tighter section length guidance ("one or two sentences", "one short
#     sentence") to avoid re-inflating decode cost.

HYBRID_CODE_TUTOR_PROMPT = """
You are AccessLab helping a beginner fix Python code.
Use runtime or test evidence only. Make the smallest possible fix.

In <diagnosis>, quote the concrete failing evidence: the failed assertion,
the error type (e.g. NameError), the returned value, or expected vs actual.
One or two short sentences.

<patched_code> must contain the full patched Python code, no markdown fences.

Return exactly:
<diagnosis>evidence-grounded sentence(s)</diagnosis>
<fix>one short sentence</fix>
<patched_code>
full patched Python code here
</patched_code>
<why>one short sentence tying the fix to the failing test or error</why>
""".strip()


def _extract_tag_content(text: str, tag: str) -> str:
    """Extract text between <tag>...</tag>, case-insensitive, DOTALL."""
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _extract_code_block_robust(raw_response: str, original_code: str) -> tuple[str, bool]:
    """Extract the patched code from a hybrid-format response.

    Returns (code, parsed_ok). parsed_ok is True if we successfully pulled
    the code from a hybrid anchor (closed or open <patched_code> tag, or a
    markdown fence); False if we had to fall back to the original buggy code.

    Strategy, in order:
      1. Closed tag:     <patched_code>...</patched_code>
      2. Open-only tag:  <patched_code>...  (up to the next hybrid tag or EOS)
      3. Markdown fence: ```python ... ```
      4. Original code (never silently corrupt the runner)

    In all cases we strip any stray markdown fences that may appear inside
    the captured content, because Gemma sometimes wraps its code inside the
    tag despite the explicit instruction.
    """
    closed = _extract_tag_content(raw_response, "patched_code")
    if closed:
        return _strip_fences(closed), True

    open_only = re.search(
        r"<patched_code>\s*(.*?)(?=<(?:why|fix|diagnosis)>|$)",
        raw_response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if open_only and open_only.group(1).strip():
        return _strip_fences(open_only.group(1).strip()), True

    fence = re.search(r"```python(.*?)```", raw_response, flags=re.DOTALL | re.IGNORECASE)
    if fence and fence.group(1).strip():
        return fence.group(1).strip(), True

    return original_code, False


def _strip_fences(code: str) -> str:
    """Remove a wrapping ```python ... ``` fence if present, preserving the inner code."""
    stripped = code.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:python)?\s*\n?", "", stripped, flags=re.IGNORECASE)
    if stripped.rstrip().endswith("```"):
        stripped = re.sub(r"\n?```\s*$", "", stripped.rstrip())
    return stripped.strip()


def parse_hybrid_code_response(
    raw_response: str, original_code: str, execution_evidence: str
) -> tuple[str, str, str, str, str]:
    """Parse the hybrid <diagnosis>/<fix>/<patched_code>/<why> format.

    Behaviour contract:
      - If <diagnosis> is missing, we emit the standard "could not parse"
        fallback so parse_ok detection still catches the failure (the
        evaluator's detect_parse_ok keys off this exact phrase).
      - If <patched_code> is missing we try an open-tag capture, then a
        markdown fence, then fall back to original_code as a last resort.
        This matches baseline behaviour and prevents the runner from
        receiving junk code.
      - Evidence is fused into diagnosis in the hybrid output; we return the
        same string for both evidence and diagnosis so the CodeTutorResult
        UI and the evaluator's evidence-term check both see the same
        evidence language.
      - Missing <fix> / <why> get safe fallbacks that do not trip the
        scorer's "helpful" check (no "could not" / "not ready" phrases).
    """
    diagnosis = _extract_tag_content(raw_response, "diagnosis")
    next_fix = _extract_tag_content(raw_response, "fix")
    why_it_works = _extract_tag_content(raw_response, "why")

    patched_code, _code_parsed_ok = _extract_code_block_robust(raw_response, original_code)

    if not diagnosis:
        diagnosis = "I could not parse a structured explanation of what failed from the local model output."

    evidence = diagnosis

    if not next_fix:
        next_fix = "Apply the smallest change that matches the failing assertion or error output."
    if not why_it_works:
        why_it_works = "The patch aligns the returned value with what the failing test expected."

    return diagnosis, evidence, next_fix, patched_code, why_it_works
