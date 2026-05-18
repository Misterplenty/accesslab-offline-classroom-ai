import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import db_connection, init_db, save_code_session, save_qa_history, utc_now_iso
from app.models.schemas import Citation, CodeTutorResult, ExecutionResult, QAResult, RuntimeCapabilities
from app.routes import router
from app.services.semantic import SQLiteSemanticIndex


SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"


class StubLLMProvider:
    backend_name = "ollama"
    runtime_label = "Ollama local runtime"
    model_name = "gemma4:e4b"

    def health_check(self) -> tuple[bool, str]:
        return True, "ready"

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            backend_name=self.backend_name,
            runtime_label=self.runtime_label,
            validation_stage="current",
            supports_streaming=True,
            token_timings_available=True,
            model_listing_available=True,
            health_probe_shape="stub health probe",
            semantic_dependency_shape="stub semantic dependency",
        )


class StubEmbeddingProvider:
    model_name = "embeddinggemma"

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "Semantic retrieval disabled in tests."

    def health_status(self) -> tuple[str, str]:
        return "disabled", "Semantic retrieval disabled in tests."

    def describe(self) -> str:
        return "stub-semantic"

    def embed_texts(self, texts):
        return []


class StubQAService:
    def __init__(self, result: QAResult, *, db_path: Path) -> None:
        self.result = result
        self.db_path = db_path

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
        history_id = save_qa_history(
            self.db_path,
            question=question,
            retrieved_chunk_ids=[citation.chunk_id for citation in self.result.citations],
            answer_text=self.result.short_answer,
            more_detail=self.result.more_detail,
            unsure=self.result.unsure,
            actor_role=actor_role,
            actor_key=actor_key,
            class_space=class_space,
            citation_list=[
                {
                    "label": citation.label,
                    "source_file": citation.source_file,
                    "page_number": citation.page_number,
                    "chunk_id": citation.chunk_id,
                    "snippet": citation.snippet,
                }
                for citation in self.result.citations
            ],
            session_data={
                "question": question,
                "answer_language": answer_language,
                "plain_language_requested": bool(plain_language_requested),
            },
        )
        self.result.history_id = history_id
        self.result.question = question
        return self.result


class StubCodeTutorService:
    def __init__(self, result: CodeTutorResult, *, db_path: Path) -> None:
        self.result = result
        self.db_path = db_path

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
        session_id = save_code_session(
            self.db_path,
            original_code=code,
            test_code=tests,
            execution_output=self.result.initial_run.combined_output or "No output.",
            patched_code=self.result.patched_code,
            patched_test_result=self.result.patched_run.combined_output or self.result.patched_run.status,
            actor_role=actor_role,
            actor_key=actor_key,
            class_space=class_space,
            session_data={
                "instruction": instruction or "",
                "original_code": code,
                "form_tests": tests or "",
                "diagnosis": self.result.diagnosis,
                "evidence": self.result.evidence,
                "next_fix": self.result.next_fix,
                "why_it_works": self.result.why_it_works,
                "patched_code": self.result.patched_code,
                "initial_run": {
                    "status": self.result.initial_run.status,
                    "return_code": self.result.initial_run.return_code,
                    "stdout": self.result.initial_run.stdout,
                    "stderr": self.result.initial_run.stderr,
                    "timed_out": self.result.initial_run.timed_out,
                    "command": self.result.initial_run.command,
                    "mode": self.result.initial_run.mode,
                    "effective_test_code": self.result.initial_run.effective_test_code,
                    "used_generated_tests": self.result.initial_run.used_generated_tests,
                    "working_directory": self.result.initial_run.working_directory,
                    "sandbox_profile": self.result.initial_run.sandbox_profile,
                    "sandbox_note": self.result.initial_run.sandbox_note,
                    "denied_by_policy": self.result.initial_run.denied_by_policy,
                },
                "patched_run": {
                    "status": self.result.patched_run.status,
                    "return_code": self.result.patched_run.return_code,
                    "stdout": self.result.patched_run.stdout,
                    "stderr": self.result.patched_run.stderr,
                    "timed_out": self.result.patched_run.timed_out,
                    "command": self.result.patched_run.command,
                    "mode": self.result.patched_run.mode,
                    "effective_test_code": self.result.patched_run.effective_test_code,
                    "used_generated_tests": self.result.patched_run.used_generated_tests,
                    "working_directory": self.result.patched_run.working_directory,
                    "sandbox_profile": self.result.patched_run.sandbox_profile,
                    "sandbox_note": self.result.patched_run.sandbox_note,
                    "denied_by_policy": self.result.patched_run.denied_by_policy,
                },
            },
        )
        self.result.session_id = session_id
        return self.result


def _build_client(
    tmp_path: Path,
    *,
    qa_result: QAResult | None = None,
    code_result: CodeTutorResult | None = None,
) -> tuple[TestClient, Settings]:
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    init_db(settings.db_path)

    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    app.include_router(router)
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=str(settings.templates_dir))
    app.state.llm_provider = StubLLMProvider()
    app.state.semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=StubEmbeddingProvider(),
    )
    if qa_result is not None:
        app.state.qa_service = StubQAService(qa_result, db_path=settings.db_path)
    if code_result is not None:
        app.state.code_tutor_service = StubCodeTutorService(code_result, db_path=settings.db_path)

    return TestClient(app), settings


def _insert_document(
    db_path: Path,
    *,
    file_name: str,
    file_type: str,
    stored_path: Path,
    chunks: list[tuple[int | None, str, str]],
) -> int:
    created_at = utc_now_iso()
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO documents (file_name, file_type, stored_path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (file_name, file_type, str(stored_path), created_at),
        )
        document_id = int(cursor.lastrowid)

        for page_number, chunk_id, chunk_text in chunks:
            connection.execute(
                """
                INSERT INTO document_chunks (
                    document_id,
                    source_file,
                    page_number,
                    chunk_id,
                    chunk_text,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (document_id, file_name, page_number, chunk_id, chunk_text, created_at),
            )

    return document_id


@pytest.mark.parametrize(
    ("path", "active_label"),
    [
        ("/", "Home"),
        ("/qa", "Ask"),
        ("/code", "Code Assist"),
    ],
)
def test_primary_pages_render_shared_shell_navigation(tmp_path, path: str, active_label: str):
    client, _ = _build_client(tmp_path)

    response = client.get(path)

    assert response.status_code == 200
    assert "AccessLab" in response.text
    assert 'href="#main-content"' in response.text
    assert 'id="main-content"' in response.text
    assert 'aria-label="Main navigation"' in response.text
    assert "Workspace" in response.text
    assert 'aria-label="Explain materials"' in response.text
    assert 'aria-label="Fix Python code"' in response.text
    assert 'aria-label="Accessibility options"' in response.text
    assert 'data-a11y-toggle="large-text"' in response.text
    assert 'data-a11y-toggle="high-contrast"' in response.text
    assert 'data-a11y-toggle="plain-language"' in response.text
    assert 'data-a11y-toggle="reduce-motion"' in response.text
    assert 'data-a11y-toggle="keyboard"' in response.text
    assert "Admin" in response.text
    assert 'href="http://testserver/static/styles.css?v=' in response.text
    assert 'src="http://testserver/static/app.js?v=' in response.text
    assert re.search(
        rf'aria-current="page"[^>]*>\s*{re.escape(active_label)}\s*</a>',
        response.text,
    )


def test_qa_page_renders_open_source_links_on_evidence_cards(tmp_path):
    qa_result = QAResult(
        question="Explain question 3.",
        short_answer="It checks one item at a time [S1].",
        more_detail="Question 3 asks students to trace the loop output [S1].",
        citations=[
            Citation(
                label="S1",
                source_file="worksheet.md",
                page_number=None,
                chunk_id="worksheet-p0-c1",
                snippet="Question 3 asks students to trace the loop output.",
            )
        ],
    )
    client, _ = _build_client(tmp_path, qa_result=qa_result)
    worksheet_path = tmp_path / "worksheet.md"
    worksheet_path.write_text("Question 3 asks students to trace the loop output.\n", encoding="utf-8")
    _insert_document(
        client.app.state.settings.db_path,
        file_name="worksheet.md",
        file_type="md",
        stored_path=worksheet_path,
        chunks=[(None, "worksheet-p0-c1", "Question 3 asks students to trace the loop output.")],
    )

    response = client.post(
        "/qa",
        data={"question": "Explain question 3.", "simplify": "0", "answer_language": "spanish"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    redirect_url = response.headers["location"]
    assert redirect_url.startswith("/qa?qa_id=")

    follow_response = client.get(redirect_url)

    assert follow_response.status_code == 200
    assert 'href="#evidence-worksheet-p0-c1-s1"' in follow_response.text
    assert re.search(
        r'<a\s+[^>]*class="[^"]*\bevidence-item__action\b[^"]*"[^>]*'
        r'href="/sources/worksheet-p0-c1\?qa_id=\d+"[^>]*'
        r'target="_blank"[^>]*'
        r'rel="noopener noreferrer"[^>]*'
        r'aria-label="Open source view for worksheet.md, evidence reference worksheet-p0-c1"[^>]*>',
        follow_response.text,
        re.S,
    )
    assert 'tabindex="-1"' in follow_response.text
    assert 'aria-controls="qa-detail"' in follow_response.text
    assert '<button class="evidence-item__action"' not in follow_response.text
    assert "Open source" in follow_response.text
    assert "Question 3 asks students to trace the loop output." in follow_response.text


def test_saved_qa_result_get_route_renders_from_history(tmp_path):
    qa_result = QAResult(
        question="Explain question 3.",
        short_answer="It checks one item at a time [S1].",
        more_detail="Question 3 asks students to trace the loop output [S1].",
        citations=[
            Citation(
                label="S1",
                source_file="worksheet.md",
                page_number=None,
                chunk_id="worksheet-p0-c1",
                snippet="Question 3 asks students to trace the loop output.",
            )
        ],
    )
    client, settings = _build_client(tmp_path, qa_result=qa_result)
    worksheet_path = tmp_path / "worksheet.md"
    worksheet_path.write_text("Question 3 asks students to trace the loop output.\n", encoding="utf-8")
    _insert_document(
        settings.db_path,
        file_name="worksheet.md",
        file_type="md",
        stored_path=worksheet_path,
        chunks=[(None, "worksheet-p0-c1", "Question 3 asks students to trace the loop output.")],
    )
    response = client.post(
        "/qa",
        data={"question": "Explain question 3.", "simplify": "0"},
        follow_redirects=False,
    )

    qa_id = int(response.headers["location"].split("=", 1)[1])
    saved_row = None
    with db_connection(settings.db_path) as connection:
        saved_row = connection.execute(
            "SELECT question, answer_text, more_detail, unsure FROM qa_history WHERE id = ?",
            (qa_id,),
        ).fetchone()

    assert saved_row is not None
    assert saved_row["question"] == "Explain question 3."
    assert saved_row["answer_text"] == "It checks one item at a time [S1]."
    assert saved_row["more_detail"] == "Question 3 asks students to trace the loop output [S1]."
    assert saved_row["unsure"] == 0

    get_response = client.get(f"/qa?qa_id={qa_id}")

    assert get_response.status_code == 200
    assert "Saved answer reopened" in get_response.text
    assert "It checks one item at a time" in get_response.text
    assert f'href="/sources/worksheet-p0-c1?qa_id={qa_id}"' in get_response.text


def test_code_page_post_redirects_to_saved_session_route(tmp_path):
    code_result = CodeTutorResult(
        diagnosis="The function subtracts when the test expects addition.",
        evidence='Initial run evidence: "AssertionError: assert -1 == 5"',
        next_fix="Replace subtraction with addition.",
        patched_code="def add_numbers(a, b):\n    return a + b\n",
        why_it_works="The function now returns the sum the assertion expected.",
        initial_run=ExecutionResult(
            status="completed",
            return_code=1,
            stdout="",
            stderr="AssertionError: assert -1 == 5",
            timed_out=False,
            command=["python", "-m", "pytest"],
            mode="tests",
            effective_test_code="assert add_numbers(2, 3) == 5",
            used_generated_tests=False,
        ),
        patched_run=ExecutionResult(
            status="completed",
            return_code=0,
            stdout="1 passed",
            stderr="",
            timed_out=False,
            command=["python", "-m", "pytest"],
            mode="tests",
            effective_test_code="assert add_numbers(2, 3) == 5",
            used_generated_tests=False,
        ),
    )
    client, _ = _build_client(tmp_path, code_result=code_result)

    response = client.post(
        "/code",
        data={
            "code": "def add_numbers(a, b):\n    return a - b\n",
            "tests": "assert add_numbers(2, 3) == 5",
            "instruction": "Explain what failed in simple language.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    redirect_url = response.headers["location"]
    assert redirect_url.startswith("/code?session_id=")

    follow_response = client.get(redirect_url)

    assert follow_response.status_code == 200
    assert "Saved code review reopened" in follow_response.text
    assert "Replace subtraction with addition." in follow_response.text
    assert "return a + b" in follow_response.text
    assert "1 passed" in follow_response.text
    assert 'data-disclosure-target="code-evidence"' in follow_response.text
    assert 'data-read-aloud-target="code-explanation-text"' in follow_response.text


def test_source_view_route_returns_pdf_page_context_and_raw_pdf_link(tmp_path):
    client, settings = _build_client(tmp_path)
    pdf_path = SAMPLE_DATA_DIR / "python_loops_notes.pdf"
    document_id = _insert_document(
        settings.db_path,
        file_name="python_loops_notes.pdf",
        file_type="pdf",
        stored_path=pdf_path,
        chunks=[
            (
                2,
                "notes-p2-c1",
                "Page 2 says a for loop checks one value at a time before moving to the next.",
            ),
            (
                2,
                "notes-p2-c2",
                "The example shows the loop visiting each number in order.",
            ),
        ],
    )

    response = client.get("/sources/notes-p2-c1")

    assert response.status_code == 200
    assert "python_loops_notes.pdf" in response.text
    assert "Page 2" in response.text
    assert "notes-p2-c1" in response.text
    assert "notes-p2-c2" in response.text
    assert "Open original PDF" in response.text
    assert f'/documents/{document_id}/file#page=2' in response.text


def test_source_view_route_keeps_return_link_to_saved_qa_state(tmp_path):
    client, settings = _build_client(tmp_path)
    md_path = tmp_path / "worksheet.md"
    md_path.write_text("Question 3 asks students to trace the loop output.\n", encoding="utf-8")
    _insert_document(
        settings.db_path,
        file_name="worksheet.md",
        file_type="md",
        stored_path=md_path,
        chunks=[(None, "worksheet-p0-c1", "Question 3 asks students to trace the loop output.")],
    )

    response = client.get("/sources/worksheet-p0-c1?qa_id=9")

    assert response.status_code == 200
    assert 'href="/qa?qa_id=9"' in response.text


def test_source_view_route_returns_markdown_excerpt_with_highlight(tmp_path):
    client, settings = _build_client(tmp_path)
    md_path = tmp_path / "worksheet.md"
    md_path.write_text(
        "# Worksheet\n\n"
        "Question 3 asks students to explain why a for loop checks each item one by one.\n\n"
        "The answer should mention that the loop repeats the same step for every value.\n",
        encoding="utf-8",
    )
    document_id = _insert_document(
        settings.db_path,
        file_name="worksheet.md",
        file_type="md",
        stored_path=md_path,
        chunks=[
            (
                None,
                "worksheet-p0-c1",
                "Question 3 asks students to explain why a for loop checks each item one by one.",
            )
        ],
    )

    response = client.get("/sources/worksheet-p0-c1")

    assert response.status_code == 200
    assert "worksheet.md" in response.text
    assert "Whole file" in response.text
    assert "worksheet-p0-c1" in response.text
    assert "<mark>Question 3 asks students to explain why a for loop checks each item one by one.</mark>" in response.text
    assert f'/documents/{document_id}/file' in response.text
    assert str(md_path) not in response.text
    assert "Stored locally in this AccessLab workspace." in response.text


def test_source_view_route_returns_text_excerpt_with_highlight(tmp_path):
    client, settings = _build_client(tmp_path)
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text(
        "A for loop checks one value at a time before moving to the next.\n"
        "Students can trace the output by following each repeated step.\n",
        encoding="utf-8",
    )
    document_id = _insert_document(
        settings.db_path,
        file_name="notes.txt",
        file_type="txt",
        stored_path=txt_path,
        chunks=[
            (
                None,
                "notes-p0-c1",
                "A for loop checks one value at a time before moving to the next.",
            )
        ],
    )

    response = client.get("/sources/notes-p0-c1")

    assert response.status_code == 200
    assert "notes.txt" in response.text
    assert "TXT" in response.text
    assert "Whole file" in response.text
    assert "notes-p0-c1" in response.text
    assert "<mark>A for loop checks one value at a time before moving to the next.</mark>" in response.text
    assert f'/documents/{document_id}/file' in response.text


def test_source_view_handles_missing_local_file_gracefully(tmp_path):
    client, settings = _build_client(tmp_path)
    missing_path = tmp_path / "missing.txt"
    _insert_document(
        settings.db_path,
        file_name="missing.txt",
        file_type="txt",
        stored_path=missing_path,
        chunks=[(None, "missing-p0-c1", "A loop repeats the same step for each item.")],
    )

    response = client.get("/sources/missing-p0-c1")

    assert response.status_code == 200
    assert "missing.txt" in response.text
    assert "original local file is unavailable" in response.text
    assert "A loop repeats the same step for each item." in response.text


def test_source_view_returns_404_for_unknown_chunk(tmp_path):
    client, _ = _build_client(tmp_path)

    response = client.get("/sources/not-a-real-chunk")

    assert response.status_code == 404
    assert "Source reference not found" in response.text
    assert "not-a-real-chunk" in response.text


def test_document_file_route_serves_original_file_inline(tmp_path):
    client, settings = _build_client(tmp_path)
    pdf_path = SAMPLE_DATA_DIR / "python_loops_notes.pdf"
    document_id = _insert_document(
        settings.db_path,
        file_name="python_loops_notes.pdf",
        file_type="pdf",
        stored_path=pdf_path,
        chunks=[(1, "notes-p1-c1", "A loop checks each item one by one.")],
    )

    response = client.get(f"/documents/{document_id}/file")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "inline" in response.headers["content-disposition"]


def test_source_and_document_routes_stay_inside_current_class_space(tmp_path):
    client, settings = _build_client(tmp_path)
    md_path = tmp_path / "history.md"
    md_path.write_text("History class discusses timelines.\n", encoding="utf-8")
    created_at = utc_now_iso()
    with db_connection(settings.db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO documents (file_name, file_type, stored_path, class_space, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("history.md", "md", str(md_path), "other-class", created_at),
        )
        document_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO document_chunks (
                document_id,
                source_file,
                page_number,
                chunk_id,
                chunk_text,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                "history.md",
                None,
                "history-p0-c1",
                "History class discusses timelines.",
                created_at,
            ),
        )

    source_response = client.get("/sources/history-p0-c1")
    file_response = client.get(f"/documents/{document_id}/file")

    assert source_response.status_code == 404
    assert "Source reference not found" in source_response.text
    assert file_response.status_code == 404
