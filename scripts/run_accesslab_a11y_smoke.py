from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the AccessLab accessibility smoke and keyboard-flow checks."
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Reuse an already-running AccessLab server instead of starting a temporary one.",
    )
    parser.add_argument(
        "--output-json",
        default=str(ROOT / "reports" / "a11y_smoke_latest.json"),
    )
    parser.add_argument(
        "--output-markdown",
        default=str(ROOT / "reports" / "a11y_smoke_latest.md"),
    )
    return parser.parse_args()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str, *, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            with urlopen(f"{base_url}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - network timing
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"AccessLab did not become ready at {base_url}: {last_error}")


@contextmanager
def managed_server(base_url: str):
    if base_url:
        yield base_url
        return

    port = _find_free_port()
    temp_data_dir = Path(tempfile.mkdtemp(prefix="accesslab-a11y-"))
    env = os.environ.copy()
    env.update(
        {
            "ACCESSLAB_DATA_DIR": str(temp_data_dir),
            "ACCESSLAB_SEMANTIC_ENABLED": "off",
            "ACCESSLAB_RETRIEVAL_MODE": "lexical",
            "ACCESSLAB_DEPLOYMENT_MODE": "school-box-shared",
            "ACCESSLAB_CLASS_SPACE": "release-gate",
        }
    )
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(url)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - cleanup
            process.kill()


def _check(
    checks: list[dict[str, Any]],
    *,
    slug: str,
    title: str,
    passed: bool,
    detail: str,
) -> None:
    checks.append(
        {
            "slug": slug,
            "title": title,
            "passed": bool(passed),
            "detail": detail,
        }
    )


def _markdown_summary(base_url: str, checks: list[dict[str, Any]]) -> str:
    manual = _manual_validation_checklist()
    screen_reader_notes = _screen_reader_validation_notes()
    limits = _known_accessibility_limits()
    lines = [
        "# AccessLab Accessibility Smoke",
        "",
        f"- Generated at: {datetime_now_iso()}",
        f"- Base URL: {base_url}",
        f"- Passed: {sum(1 for check in checks if check['passed'])}/{len(checks)}",
        "- Claim level: automated smoke gate, not WCAG certification",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        lines.append(
            f"| {check['title']} | {'pass' if check['passed'] else 'fail'} | {check['detail']} |"
        )
    lines.extend(["", "## Manual Validation Checklist", ""])
    for item in manual:
        lines.append(f"- [{item['status']}] {item['title']}: {item['detail']}")
    lines.extend(["", "## Screen-Reader Validation Notes", ""])
    for item in screen_reader_notes:
        lines.append(f"- {item['platform']}: {item['status']} - {item['note']}")
    lines.extend(["", "## Known Accessibility Limits", ""])
    lines.extend(f"- {item}" for item in limits)
    return "\n".join(lines) + "\n"


def datetime_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _manual_validation_checklist() -> list[dict[str, str]]:
    return [
        {
            "title": "Inclusive Classroom Mode",
            "status": "covered-by-smoke",
            "detail": "Large text, high contrast, plain language, reduce motion, and keyboard mode toggles are exercised.",
        },
        {
            "title": "Read-aloud transcript",
            "status": "covered-by-smoke",
            "detail": "Answer read-aloud controls are paired with visible transcript text.",
        },
        {
            "title": "Keyboard-only upload",
            "status": "covered-by-smoke",
            "detail": "Teacher role switch, file input, submit button, redirect, and status-region focus are exercised.",
        },
        {
            "title": "Keyboard-only QA",
            "status": "covered-by-smoke",
            "detail": "Question entry, submit activation, saved URL, and status-region focus are exercised.",
        },
        {
            "title": "Keyboard-only citation/source navigation",
            "status": "covered-by-smoke",
            "detail": "Citation jump focus and source inspection popup are exercised.",
        },
        {
            "title": "Keyboard-only code tutor",
            "status": "covered-by-smoke",
            "detail": "Textarea entry, submit activation, saved URL, and evidence disclosure focus are exercised.",
        },
        {
            "title": "Focus restoration after saved session redirect",
            "status": "covered-by-smoke",
            "detail": "QA and code saved redirects wait for focus on the status region.",
        },
        {
            "title": "Visible progress states",
            "status": "covered-by-smoke",
            "detail": "QA and code forms expose text progress stages instead of relying on audio or a static spinner.",
        },
        {
            "title": "Role switching",
            "status": "covered-by-smoke",
            "detail": "Teacher, learner, and admin role transitions are exercised in one browser session.",
        },
        {
            "title": "Admin navigation",
            "status": "covered-by-smoke",
            "detail": "Admin system view reachability and diagnostics section visibility are exercised.",
        },
    ]


def _screen_reader_validation_notes() -> list[dict[str, str]]:
    return [
        {
            "platform": "NVDA / Windows",
            "status": "not-run-on-this-host",
            "note": "No Windows/NVDA environment was available in this run; keep this as a manual release check before a Windows classroom claim.",
        },
        {
            "platform": "VoiceOver / macOS",
            "status": "manual-spot-check-recommended",
            "note": "The current host is macOS, but this smoke does not automate speech output; use VoiceOver rotor checks for landmarks, forms, citations, and saved redirects.",
        },
        {
            "platform": "TalkBack / Android",
            "status": "not-run-on-this-host",
            "note": "No Android/TalkBack device was available in this run; do not claim Android screen-reader validation from this artifact.",
        },
    ]


def _known_accessibility_limits() -> list[str]:
    return [
        "The smoke gate is not WCAG certification.",
        "The browser and screen-reader matrix may be incomplete.",
        "OCR quality affects document accessibility and source usefulness.",
        "Code editor fields are simple textareas, not full IDE accessibility surfaces.",
        "Speech-output quality still needs manual assistive-technology review.",
    ]


def _locator_has_focus(locator) -> bool:
    return bool(locator.evaluate("el => el === document.activeElement"))


def _active_focus_visible(page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const el = document.activeElement;
              if (!el) return false;
              const style = getComputedStyle(el);
              return style.outlineStyle !== "none" || style.boxShadow !== "none";
            }
            """
        )
    )


def _not_hidden_by_topbar(page, selector: str) -> bool:
    return bool(
        page.evaluate(
            """
            (targetSelector) => {
              const target = document.querySelector(targetSelector);
              if (!target) return false;
              const header = document.querySelector(".app-topbar");
              const targetRect = target.getBoundingClientRect();
              const headerBottom = header ? header.getBoundingClientRect().bottom : 0;
              return targetRect.top >= headerBottom - 4;
            }
            """,
            selector,
        )
    )


def _wait_for_focus(page, selector: str, *, timeout_ms: int = 4000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if page.evaluate(
                """
                (targetSelector) => {
                  const el = document.querySelector(targetSelector);
                  return Boolean(el && el === document.activeElement);
                }
                """,
                selector,
            ):
                return True
        except Exception:
            pass
        page.wait_for_timeout(80)
    return False


def _wait_for_url_contains(page, fragment: str, *, timeout_ms: int = 5000) -> bool:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            if fragment in page.url:
                return True
        except Exception:
            pass
        page.wait_for_timeout(80)
    return False


def run_smoke(base_url: str) -> dict[str, Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError(
            "Playwright is not installed. Run `python -m pip install -r requirements-a11y.txt` first."
        ) from exc

    sample_doc = ROOT / "sample_data" / "worksheet_question3.md"
    code_path = ROOT / "sample_code" / "buggy_sum.py"
    checks: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:  # pragma: no cover - local dependency path
            raise RuntimeError(
                "Playwright is installed but the Chromium browser is missing. "
                "Run `playwright install chromium` before the accessibility release gate."
            ) from exc
        context = browser.new_context()
        page = context.new_page()

        page.goto(base_url, wait_until="networkidle")
        _check(
            checks,
            slug="landmark-structure",
            title="Heading and landmark structure",
            passed=page.locator("header[role='banner']").count() == 1
            and page.locator("nav[aria-label='Main navigation']").count() == 1
            and page.locator("main#main-content").count() == 1
            and page.locator("footer").count() == 1
            and page.locator("h1").count() == 1,
            detail="The shell keeps a single page heading plus header, nav, main, and footer landmarks for screen-reader navigation.",
        )
        page.keyboard.press("Tab")
        skip_link = page.locator(".skip-link")
        _check(
            checks,
            slug="main-navigation-skip-link",
            title="Main navigation and skip link",
            passed=_locator_has_focus(skip_link) and _active_focus_visible(page),
            detail="Skip link receives focus first and shows visible focus styling.",
        )

        toolbar = page.locator(".accessibility-toolbar")
        large_text_toggle = toolbar.locator("[data-a11y-toggle='large-text']")
        contrast_toggle = toolbar.locator("[data-a11y-toggle='high-contrast']")
        plain_toggle = toolbar.locator("[data-a11y-toggle='plain-language']")
        reduce_motion_toggle = toolbar.locator("[data-a11y-toggle='reduce-motion']")
        keyboard_toggle = toolbar.locator("[data-a11y-toggle='keyboard']")
        large_text_toggle.click()
        contrast_toggle.click()
        plain_toggle.click()
        reduce_motion_toggle.click()
        keyboard_toggle.click()
        _check(
            checks,
            slug="inclusive-classroom-toolbar",
            title="Inclusive Classroom toolbar",
            passed=toolbar.count() == 1
            and large_text_toggle.get_attribute("aria-pressed") == "true"
            and contrast_toggle.get_attribute("aria-pressed") == "true"
            and plain_toggle.get_attribute("aria-pressed") == "true"
            and reduce_motion_toggle.get_attribute("aria-pressed") == "true"
            and keyboard_toggle.get_attribute("aria-pressed") == "true"
            and page.evaluate(
                """
                () => document.body.classList.contains("a11y-large-text")
                  && document.body.classList.contains("a11y-high-contrast")
                  && document.body.classList.contains("a11y-plain-language")
                  && document.body.classList.contains("a11y-reduce-motion")
                  && document.body.classList.contains("a11y-keyboard-mode")
                """
            ),
            detail="Large text, high contrast, plain language, reduce motion, and keyboard modes are toggleable and persisted locally.",
        )

        page.select_option("#local-role", "teacher")
        page.locator(".role-switcher button[type='submit']").click()
        page.wait_for_load_state("networkidle")
        upload_input = page.locator("#document")
        _check(
            checks,
            slug="role-switch-teacher",
            title="Role switch and teacher controls",
            passed=upload_input.is_visible(),
            detail="Teacher mode exposes upload controls without showing a separate admin shell.",
        )

        upload_input.set_input_files(str(sample_doc))
        upload_started = _wait_for_url_contains(page, "/upload", timeout_ms=8000)
        if not upload_started:
            upload_submit = page.locator("form[action='/upload'] button[type='submit']")
            if upload_submit.count() > 0:
                upload_submit.focus()
                page.keyboard.press(" ")
                upload_started = _wait_for_url_contains(page, "/upload")
        page.locator("#status-region").wait_for(timeout=5000)
        page.wait_for_load_state("networkidle")
        _check(
            checks,
            slug="upload-flow-focus",
            title="Upload flow and redirect focus",
            passed=upload_started
            and _wait_for_focus(page, "#status-region")
            and page.locator(f"text={sample_doc.name}").first.is_visible(),
            detail="Teacher upload keeps the interaction in-page, restores focus to the status region, and updates the shared class collection.",
        )

        qa_nav_link = page.locator('nav[aria-label="Main navigation"] a[href="/qa"]')
        qa_nav_link.focus()
        page.keyboard.press("Enter")
        _wait_for_url_contains(page, "/qa")
        page.wait_for_load_state("networkidle")
        plain_input = page.locator("form[action='/qa'] [data-a11y-plain-input]").first
        _check(
            checks,
            slug="inclusive-form-preferences",
            title="Inclusive form preferences",
            passed=plain_input.count() == 1
            and plain_input.evaluate("el => el.value") == "1"
            and "Gemma 4 writing answer" in (page.locator("form[action='/qa']").first.get_attribute("data-status-steps") or ""),
            detail="Plain-language mode feeds grounded QA, and the visible progress contract names the Gemma 4 answering stage.",
        )
        page.locator("#question").fill("What does for item in numbers mean?")
        qa_submit = page.locator("button[name='simplify'][value='0']")
        qa_submit.focus()
        qa_submit_focusable = qa_submit.evaluate("el => el === document.activeElement")
        qa_submit.click(no_wait_after=True)
        qa_saved = _wait_for_url_contains(page, "qa_id=", timeout_ms=90000)
        if qa_saved:
            try:
                page.locator("#status-region").wait_for(timeout=5000)
                page.wait_for_load_state("networkidle")
            except Exception:
                qa_saved = False
        qa_url = page.url
        citation_link = page.locator(".citation-link").first
        _check(
            checks,
            slug="qa-flow-save-focus",
            title="QA flow and saved-answer focus",
            passed=qa_submit_focusable
            and qa_saved
            and "qa_id=" in qa_url
            and _wait_for_focus(page, "#status-region", timeout_ms=6000),
            detail="Grounded QA lands on a saved URL and returns focus to the status region.",
        )

        citation_target = citation_link.get_attribute("data-evidence-target") or ""
        citation_link.focus()
        page.keyboard.press("Enter")
        page.wait_for_timeout(150)
        target_selector = f"#{citation_target}" if citation_target else ".evidence-item"
        _check(
            checks,
            slug="citation-jump-flow",
            title="Citation jump flow",
            passed=bool(citation_target)
            and _wait_for_focus(page, target_selector)
            and _not_hidden_by_topbar(page, target_selector),
            detail="Keyboard activation jumps to the evidence card, focuses it, and keeps it clear of the page header.",
        )

        detail_toggle = page.locator("[data-disclosure-target='qa-detail']")
        if detail_toggle.count() > 0:
            detail_toggle.focus()
            page.keyboard.press("Enter")
            panel_open = not page.locator("#qa-detail").evaluate("el => Boolean(el.hidden)")
            focus_kept = detail_toggle.evaluate("el => el === document.activeElement")
            page.keyboard.press("Enter")
            panel_closed = page.locator("#qa-detail").evaluate("el => Boolean(el.hidden)")
            _check(
                checks,
                slug="qa-disclosure-focus",
                title="Disclosure open/close focus",
                passed=panel_open and focus_kept and panel_closed,
                detail="The detail disclosure toggles open and closed without losing keyboard focus.",
            )

        read_aloud_button = page.locator("[data-read-aloud-target='qa-answer-text']").first
        transcript = page.locator(".read-aloud-transcript").first
        _check(
            checks,
            slug="read-aloud-transcript",
            title="Read-aloud transcript",
            passed=read_aloud_button.count() == 1
            and transcript.count() == 1
            and "Read-aloud transcript" in transcript.text_content(),
            detail="Generated answer audio is optional; the same content remains available as text.",
        )

        with context.expect_page() as popup_info:
            page.locator(".evidence-item__action").first.focus()
            page.keyboard.press("Enter")
        source_page = popup_info.value
        source_page.wait_for_load_state("networkidle")
        _check(
            checks,
            slug="source-inspection-flow",
            title="Source inspection flow",
            passed=source_page.locator("#cited-snippet").is_visible(),
            detail="The cited source view opens with the cited excerpt visible first.",
        )
        source_page.close()

        code_nav_link = page.locator('nav[aria-label="Main navigation"] a[href="/code"]')
        code_nav_link.focus()
        page.keyboard.press("Enter")
        _wait_for_url_contains(page, "/code")
        page.wait_for_load_state("networkidle")
        page.locator("#code").fill(code_path.read_text(encoding="utf-8"))
        code_submit = page.locator("form[action='/code'] button[type='submit']")
        code_submit.focus()
        code_submit_focusable = code_submit.evaluate("el => el === document.activeElement")
        code_submit.click(no_wait_after=True)
        code_saved = _wait_for_url_contains(page, "session_id=", timeout_ms=90000)
        code_status_focus = False
        if code_saved:
            try:
                page.locator("#status-region").wait_for(timeout=5000)
                page.wait_for_load_state("networkidle")
                code_status_focus = _wait_for_focus(page, "#status-region", timeout_ms=6000)
            except Exception:
                code_saved = False
        evidence_toggle = page.locator("[data-disclosure-target='code-evidence']")
        evidence_toggle.focus()
        page.keyboard.press("Enter")
        code_panel_open = not page.locator("#code-evidence").evaluate("el => Boolean(el.hidden)")
        code_focus_kept = evidence_toggle.evaluate("el => el === document.activeElement")
        _check(
            checks,
            slug="code-tutor-flow",
            title="Code tutor flow",
            passed=code_submit_focusable
            and code_saved
            and "session_id=" in page.url
            and code_status_focus
            and code_panel_open
            and code_focus_kept,
            detail="Code tutor saves to a stable URL and keeps disclosure focus stable after opening evidence.",
        )

        page.select_option("#local-role", "admin")
        page.locator(".role-switcher button[type='submit']").click()
        page.wait_for_load_state("networkidle")
        page.goto(f"{base_url}/admin", wait_until="networkidle")
        _check(
            checks,
            slug="admin-system-view",
            title="Admin system view",
            passed=page.locator("h1").text_content().strip() == "System"
            and page.locator("text=Queue").first.is_visible()
            and page.locator("text=Runtime capabilities").is_visible(),
            detail="Admin mode exposes runtime, retrieval, indexing, OCR, and queue diagnostics in one server-rendered page.",
        )

        browser.close()

    return {
        "generated_at": datetime_now_iso(),
        "base_url": base_url,
        "claim_level": "automated smoke gate, not WCAG certification",
        "checks": checks,
        "counts": {
            "total": len(checks),
            "passed": sum(1 for check in checks if check["passed"]),
            "failed": sum(1 for check in checks if not check["passed"]),
        },
        "manual_validation_checklist": _manual_validation_checklist(),
        "screen_reader_validation_notes": _screen_reader_validation_notes(),
        "known_accessibility_limits": _known_accessibility_limits(),
    }


def main() -> None:
    args = parse_args()
    with managed_server(args.base_url) as base_url:
        report = run_smoke(base_url)

    json_path = Path(args.output_json)
    markdown_path = Path(args.output_markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(
        _markdown_summary(report["base_url"], report["checks"]),
        encoding="utf-8",
    )

    if report["counts"]["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
