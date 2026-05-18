from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import (
    db_connection,
    get_qa_history_entry,
    init_db,
    list_session_labels,
    save_code_session,
    save_qa_history,
    utc_now_iso,
)
from app.models.schemas import CodeTutorResult, ExecutionResult, QAResult, RuntimeCapabilities
from app.routes import router
from app.services.semantic import SQLiteSemanticIndex


class StubLLMProvider:
    def __init__(self, *, ready: bool = True, message: str = "Ready with `gemma4:e4b`.") -> None:
        self.ready = ready
        self.message = message
        self.backend_name = "ollama"
        self.runtime_label = "Ollama local runtime"
        self.model_name = "gemma4:e4b"

    def health_check(self) -> tuple[bool, str]:
        return self.ready, self.message

    def describe_runtime(self) -> str:
        return f"{self.runtime_label} ({self.model_name})"

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


class StubIngestService:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc

    def ingest_upload(
        self,
        *,
        file_name: str,
        content: bytes,
        uploader_role: str = "teacher",
        visibility_scope: str = "class",
        class_space: str = "default-classroom",
    ):
        if self.exc is not None:
            raise self.exc
        raise AssertionError("StubIngestService should only be used in error-state tests.")


class StubQAService:
    def __init__(self, result: QAResult, *, db_path: Path) -> None:
        self.result = result
        self.db_path = db_path
        self.questions: list[str] = []
        self.answer_languages: list[str] = []
        self.plain_language_requests: list[bool] = []

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
        self.questions.append(question)
        self.answer_languages.append(answer_language)
        self.plain_language_requests.append(plain_language_requested)
        history_id = save_qa_history(
            self.db_path,
            question=question,
            retrieved_chunk_ids=[],
            answer_text=self.result.short_answer,
            more_detail=self.result.more_detail,
            unsure=self.result.unsure,
            result_mode=self.result.result_mode,
            actor_role=actor_role,
            actor_key=actor_key,
            class_space=class_space,
            citation_list=[],
            session_data={
                "question": question,
                "answer_language": answer_language,
                "answer_language_label": {
                    "spanish": "Spanish",
                    "french": "French",
                    "swahili": "Swahili",
                    "hindi": "Hindi",
                    "arabic": "Arabic",
                    "english": "English",
                }.get(answer_language, "Match question"),
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
        self.execution_backend = type(
            "StubExecutionBackend",
            (),
            {
                "sandbox_profile": self.result.initial_run.sandbox_profile or "audit-posix",
                "sandbox_note": self.result.initial_run.sandbox_note or "Best-effort local sandbox.",
            },
        )()

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
            execution_output=self.result.initial_run.combined_output or self.result.initial_run.stderr or "No output.",
            patched_code=self.result.patched_code,
            patched_test_result=self.result.patched_run.combined_output or self.result.patched_run.stderr or self.result.patched_run.status,
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
                "result_mode": self.result.result_mode,
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
    llm_ready: bool = True,
    llm_message: str = "Ready with `gemma4:e4b`.",
    qa_result: QAResult | None = None,
    code_result: CodeTutorResult | None = None,
    ingest_exc: Exception | None = None,
    settings_kwargs: dict | None = None,
) -> tuple[TestClient, Settings]:
    settings = Settings(data_dir=tmp_path / "data", **(settings_kwargs or {}))
    settings.ensure_directories()
    init_db(settings.db_path)

    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    app.include_router(router)
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=str(settings.templates_dir))
    app.state.llm_provider = StubLLMProvider(ready=llm_ready, message=llm_message)
    app.state.semantic_index = SQLiteSemanticIndex(
        db_path=settings.db_path,
        embedding_provider=StubEmbeddingProvider(),
    )
    app.state.ingest_service = StubIngestService(exc=ingest_exc)
    if qa_result is not None:
        app.state.qa_service = StubQAService(qa_result, db_path=settings.db_path)
    if code_result is not None:
        app.state.code_tutor_service = StubCodeTutorService(code_result, db_path=settings.db_path)
    return TestClient(app), settings


def _insert_document(db_path: Path, *, file_name: str = "worksheet.md") -> None:
    created_at = utc_now_iso()
    stored_path = db_path.parent / file_name
    stored_path.write_text("Question 3 explains loops.", encoding="utf-8")
    with db_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO documents (file_name, file_type, stored_path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (file_name, "md", str(stored_path), created_at),
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
                file_name,
                None,
                "worksheet-p0-c1",
                "Question 3 explains loops.",
                created_at,
            ),
        )


def test_upload_route_surfaces_structured_ocr_unavailable_error(tmp_path):
    client, _ = _build_client(
        tmp_path,
        ingest_exc=ValueError(
            "No readable text was found in that file. 1 page(s) looked scanned but OCR is unavailable: RapidOCR extras are not installed."
        ),
    )
    client.cookies.set("accesslab_role", "teacher")

    response = client.post(
        "/upload",
        files={"document": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 200
    assert "This scanned file needs OCR support" in response.text
    assert "Review local setup" in response.text


def test_qa_post_without_documents_shows_recovery_action(tmp_path):
    client, _ = _build_client(tmp_path)

    response = client.post(
        "/qa",
        data={"question": "Explain question 3.", "simplify": "0"},
    )

    assert response.status_code == 409
    assert "Add materials before asking a grounded question" in response.text
    assert "Go to Workspace" in response.text


def test_qa_no_match_state_renders_specific_empty_evidence_copy(tmp_path):
    qa_result = QAResult(
        question="Explain question 3.",
        short_answer="I could not find a close match in the uploaded materials.",
        more_detail="Try a more specific question or upload the worksheet page that contains the answer.",
        unsure=True,
        result_mode="no_match",
    )
    client, settings = _build_client(tmp_path, qa_result=qa_result)
    _insert_document(settings.db_path)

    response = client.post(
        "/qa",
        data={"question": "Explain question 3.", "simplify": "0"},
        follow_redirects=False,
    )
    follow_response = client.get(response.headers["location"])

    assert follow_response.status_code == 200
    assert "No close evidence match" in follow_response.text
    assert "No evidence was retrieved for this question." in follow_response.text


def test_code_blocked_state_renders_policy_notice_and_no_rerun_language(tmp_path):
    code_result = CodeTutorResult(
        diagnosis="The local runner blocked this code because it crossed the demo sandbox policy.",
        evidence="The blocked runner did not complete the submission, so no normal runtime evidence is available.",
        next_fix="Remove restricted imports and retry with a simpler local-only example.",
        patched_code="import os\n",
        why_it_works="The runner allows only a narrow beginner-Python subset.",
        initial_run=ExecutionResult(
            status="blocked",
            return_code=None,
            stdout="",
            stderr="import `os` is blocked in this local prototype runner",
            timed_out=False,
            command=[],
            mode="blocked",
            sandbox_profile="audit-posix",
            sandbox_note="Best-effort local sandbox.",
            denied_by_policy=True,
        ),
        patched_run=ExecutionResult(
            status="not_run",
            return_code=None,
            stdout="",
            stderr="No rerun was attempted because the submission was blocked.",
            timed_out=False,
            command=[],
            mode="not_run",
        ),
        result_mode="blocked",
    )
    client, _ = _build_client(tmp_path, code_result=code_result)

    response = client.post(
        "/code",
        data={"code": "import os\n", "tests": "", "instruction": ""},
        follow_redirects=False,
    )
    follow_response = client.get(response.headers["location"])

    assert follow_response.status_code == 200
    assert "Execution blocked by local sandbox policy" in follow_response.text
    assert "No rerun attempted" in follow_response.text
    assert "blocked by policy" in follow_response.text


def test_code_timeout_state_renders_timeout_notice(tmp_path):
    code_result = CodeTutorResult(
        diagnosis="The execution timed out because the loop never stops.",
        evidence="Execution timed out.",
        next_fix="Add a stopping condition.",
        patched_code="for value in range(1):\n    print(value)\n",
        why_it_works="The code now terminates cleanly.",
        initial_run=ExecutionResult(
            status="timeout",
            return_code=None,
            stdout="",
            stderr="Execution timed out.",
            timed_out=True,
            command=[],
            mode="script",
            sandbox_profile="audit-posix",
            sandbox_note="Best-effort local sandbox.",
        ),
        patched_run=ExecutionResult(
            status="completed",
            return_code=0,
            stdout="ok",
            stderr="",
            timed_out=False,
            command=[],
            mode="script",
        ),
    )
    client, _ = _build_client(tmp_path, code_result=code_result)

    response = client.post(
        "/code",
        data={"code": "while True:\n    pass\n", "tests": "", "instruction": ""},
        follow_redirects=False,
    )
    follow_response = client.get(response.headers["location"])

    assert follow_response.status_code == 200
    assert "Original run timed out" in follow_response.text
    assert "Passed local test run" in follow_response.text


def test_code_form_starts_blank_without_sample_add_numbers(tmp_path):
    client, _ = _build_client(tmp_path)

    response = client.get("/code")

    assert response.status_code == 200
    assert "def add_numbers" not in response.text
    assert "test_add_numbers" not in response.text


def test_saved_mismatched_code_session_does_not_show_unrelated_patch(tmp_path):
    client, settings = _build_client(tmp_path)
    session_id = save_code_session(
        settings.db_path,
        original_code="Print(helloworld)\n",
        test_code=(
            "from submission import add_numbers\n\n"
            "def test_add_numbers():\n"
            "    assert add_numbers(2, 3) == 5\n"
        ),
        execution_output="NameError: name 'Print' is not defined",
        patched_code="def add_numbers(a, b):\n    return a + b\n",
        patched_test_result="1 passed",
        actor_role="learner",
        actor_key="local-user",
        class_space=settings.class_space,
        session_data={
            "original_code": "Print(helloworld)\n",
            "form_tests": (
                "from submission import add_numbers\n\n"
                "def test_add_numbers():\n"
                "    assert add_numbers(2, 3) == 5\n"
            ),
            "patched_code": "def add_numbers(a, b):\n    return a + b\n",
            "result_mode": "completed",
        },
    )
    client.cookies.set("accesslab_role", "teacher")

    response = client.get(f"/code?session_id={session_id}")

    assert response.status_code == 200
    assert "Tests do not match this code" in response.text
    assert "def add_numbers" not in response.text
    assert "Print(helloworld)" in response.text


def test_home_defaults_to_learner_role_and_renders_role_switcher(tmp_path):
    client, _ = _build_client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "Local role" in response.text
    assert "Inclusive Classroom" in response.text
    assert 'data-a11y-toggle="high-contrast"' in response.text
    assert 'value="learner" selected' in response.text
    assert "Upload locked" in response.text


def test_upload_route_blocks_learner_role(tmp_path):
    client, _ = _build_client(tmp_path)

    response = client.post(
        "/upload",
        files={"document": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 403
    assert "Teacher or admin access needed" in response.text
    assert "Switch to Teacher or Admin" in response.text


def test_role_switch_route_sets_cookie_and_redirects(tmp_path):
    client, _ = _build_client(tmp_path)

    response = client.post(
        "/role",
        data={"role": "teacher", "next_path": "/qa"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/qa"
    assert "accesslab_role=teacher" in response.headers.get("set-cookie", "")


def test_saved_qa_view_marks_status_region_as_focus_target(tmp_path):
    qa_result = QAResult(
        question="Explain question 3.",
        short_answer="Question 3 uses a loop to visit one item at a time. [S1]",
        more_detail="The answer stays tied to local evidence.",
        unsure=False,
        result_mode="answered",
    )
    client, settings = _build_client(tmp_path, qa_result=qa_result)
    _insert_document(settings.db_path)

    response = client.post(
        "/qa",
        data={"question": "Explain question 3.", "simplify": "0"},
        follow_redirects=False,
    )
    follow_response = client.get(response.headers["location"])

    assert follow_response.status_code == 200
    assert 'data-focus-target="status-region"' in follow_response.text
    assert 'id="status-region"' in follow_response.text


def test_learner_saved_qa_hides_proof_and_uses_link_for_new_question(tmp_path):
    qa_result = QAResult(
        question="Explain question 3.",
        short_answer="Question 3 uses a loop to visit one item at a time. [S1]",
        more_detail="The answer stays tied to local evidence.",
        unsure=False,
        result_mode="answered",
    )
    client, settings = _build_client(tmp_path, qa_result=qa_result)
    _insert_document(settings.db_path)

    response = client.post(
        "/qa",
        data={"question": "Explain question 3.", "simplify": "0"},
        follow_redirects=False,
    )
    follow_response = client.get(response.headers["location"])

    assert follow_response.status_code == 200
    assert 'aria-label="Answer trust details"' not in follow_response.text
    assert "Readable mode" not in follow_response.text
    assert "<summary>Ask another question</summary>" not in follow_response.text
    assert 'href="/qa">Ask another question</a>' in follow_response.text


def test_teacher_saved_qa_keeps_proof_panel(tmp_path):
    client, settings = _build_client(tmp_path)
    client.cookies.set("accesslab_role", "teacher")
    qa_id = save_qa_history(
        settings.db_path,
        question="Explain loops",
        retrieved_chunk_ids=[],
        answer_text="Loops go item by item.",
        more_detail="",
        unsure=False,
        result_mode="answered",
        actor_role="learner",
        actor_key="user-other1",
        class_space=settings.class_space,
        citation_list=[],
    )

    response = client.get(f"/qa?qa_id={qa_id}")

    assert response.status_code == 200
    assert 'aria-label="Answer trust details"' in response.text
    assert "Proof" in response.text


def test_qa_language_selection_keeps_saved_and_displayed_question_clean(tmp_path):
    clean_question = "What does the worksheet say about loops?"
    qa_result = QAResult(
        question=clean_question,
        short_answer="Los bucles revisan cada elemento local uno por uno. [S1]",
        more_detail="",
        unsure=False,
        result_mode="answered",
    )
    client, settings = _build_client(tmp_path, qa_result=qa_result)
    _insert_document(settings.db_path)

    response = client.post(
        "/qa",
        data={
            "question": clean_question,
            "simplify": "0",
            "answer_language": "spanish",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    qa_service = client.app.state.qa_service
    assert qa_service.questions == [clean_question]
    assert qa_service.answer_languages == ["spanish"]
    assert qa_service.plain_language_requests == [False]

    qa_id = int(response.headers["location"].split("=", 1)[1])
    saved = get_qa_history_entry(settings.db_path, qa_id)
    assert saved is not None
    assert saved["question"] == clean_question
    assert saved["session_data"]["answer_language"] == "spanish"
    assert saved["session_data"]["plain_language_requested"] is False

    follow_response = client.get(response.headers["location"])
    assert follow_response.status_code == 200
    assert clean_question in follow_response.text
    assert "Answer in Spanish" not in follow_response.text
    assert "while citing the local classroom sources" not in follow_response.text


def test_qa_plain_language_mode_keeps_saved_question_clean(tmp_path):
    clean_question = "What does the worksheet say about loops?"
    qa_result = QAResult(
        question=clean_question,
        short_answer="A loop checks items one at a time. [S1]",
        more_detail="",
        unsure=False,
        result_mode="answered",
    )
    client, settings = _build_client(tmp_path, qa_result=qa_result)
    _insert_document(settings.db_path)

    response = client.post(
        "/qa",
        data={
            "question": clean_question,
            "simplify": "1",
            "answer_language": "auto",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    qa_service = client.app.state.qa_service
    assert qa_service.questions == [clean_question]
    assert qa_service.plain_language_requests == [True]

    qa_id = int(response.headers["location"].split("=", 1)[1])
    saved = get_qa_history_entry(settings.db_path, qa_id)
    assert saved is not None
    assert saved["question"] == clean_question
    assert saved["session_data"]["plain_language_requested"] is True

    follow_response = client.get(response.headers["location"])
    assert follow_response.status_code == 200
    assert clean_question in follow_response.text
    assert "plain, simple language" not in follow_response.text


def test_admin_route_requires_admin_role(tmp_path):
    client, _ = _build_client(tmp_path)

    response = client.get("/admin")

    assert response.status_code == 403
    assert "Admin access needed" in response.text


def test_admin_route_renders_semantic_and_queue_sections(tmp_path):
    client, _ = _build_client(
        tmp_path,
        settings_kwargs={
            "deployment_mode": "school-box-shared",
            "class_space": "history-lab",
        },
    )
    client.cookies.set("accesslab_role", "admin")

    response = client.get("/admin")

    assert response.status_code == 200
    assert "System" in response.text
    assert "Status" in response.text
    assert "Queue" in response.text
    assert "Runtime capabilities" in response.text
    assert "School AI box" in response.text
    assert "history lab" in response.text


def test_judge_demo_route_seeds_cached_flow(tmp_path):
    client, settings = _build_client(
        tmp_path,
        settings_kwargs={
            "class_space": "judge-demo-class",
        },
    )

    response = client.get("/judge-demo")
    second_response = client.get("/judge-demo")

    assert response.status_code == 200
    assert second_response.status_code == 200
    assert "Judge demo" in response.text
    assert "Ask a grounded classroom question" in response.text
    assert "Inspect the cited source" in response.text
    assert "Fix beginner Python" in response.text
    assert 'href="/proofs"' in response.text

    with db_connection(settings.db_path) as connection:
        document_count = connection.execute(
            "SELECT COUNT(*) FROM documents WHERE class_space = ?",
            (settings.class_space,),
        ).fetchone()[0]
        qa_count = connection.execute(
            "SELECT COUNT(*) FROM qa_history WHERE class_space = ?",
            (settings.class_space,),
        ).fetchone()[0]
        code_count = connection.execute(
            "SELECT COUNT(*) FROM code_sessions WHERE class_space = ?",
            (settings.class_space,),
        ).fetchone()[0]
        polluted_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM qa_history
            WHERE class_space = ?
              AND (
                question LIKE '%Answer in %'
                OR question LIKE '%plain language%'
                OR question LIKE '%while citing the local classroom sources%'
              )
            """,
            (settings.class_space,),
        ).fetchone()[0]

    assert document_count == 5
    assert qa_count == 2
    assert code_count == 1
    assert polluted_count == 0


def test_admin_proofs_route_surfaces_offline_and_ollama_panels(tmp_path):
    client, _ = _build_client(tmp_path)
    client.cookies.set("accesslab_role", "admin")

    response = client.get("/admin/proofs")

    assert response.status_code == 200
    assert "Proof Dashboard" in response.text
    assert "Local/offline proof" in response.text
    assert "Accessibility proof" in response.text
    assert "Inclusive classroom" in response.text
    assert "Ollama runtime proof" in response.text
    assert "Future of Education + Ollama" in response.text
    assert "Cloud API key" in response.text


def test_public_proofs_route_is_read_only_for_judges(tmp_path):
    client, settings = _build_client(tmp_path)

    response = client.get("/proofs")

    assert response.status_code == 200
    assert "Proof Dashboard" in response.text
    assert "Evaluation Scorecard" in response.text
    assert "Code runner boundary" in response.text
    assert "Judge bundle freshness" in response.text
    assert "reports/" in response.text
    assert str(settings.base_dir) not in response.text

    admin_response = client.get("/admin/proofs")
    assert admin_response.status_code == 403


def test_admin_class_space_migration_preview_renders_counts(tmp_path):
    client, settings = _build_client(tmp_path)
    client.cookies.set("accesslab_role", "admin")
    _insert_document(settings.db_path)

    response = client.post(
        "/admin/class-space-migration",
        data={
            "from_class_space": settings.class_space,
            "to_class_space": "new-history-lab",
            "include_sessions": "1",
            "action": "preview",
        },
    )

    assert response.status_code == 200
    assert "Dry-run preview ready" in response.text
    assert "Class-space reassignment" in response.text
    assert "new-history-lab" in response.text


def test_teacher_can_add_local_quality_label_to_saved_qa_session(tmp_path):
    client, settings = _build_client(tmp_path)
    client.cookies.set("accesslab_role", "teacher")
    qa_id = save_qa_history(
        settings.db_path,
        question="Explain loops",
        retrieved_chunk_ids=[],
        answer_text="Loops go item by item.",
        more_detail="",
        unsure=False,
        result_mode="answered",
        actor_role="learner",
        actor_key="user-other1",
        class_space=settings.class_space,
        citation_list=[],
    )

    response = client.post(
        "/session-labels",
        data={
            "source_type": "qa",
            "source_id": qa_id,
            "label": "needs-review",
            "note": "Needs shorter answer.",
            "redirect_to": f"/qa?qa_id={qa_id}",
        },
        follow_redirects=False,
    )

    labels = list_session_labels(
        settings.db_path,
        source_type="qa",
        source_id=qa_id,
        class_space=settings.class_space,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/qa?qa_id={qa_id}"
    assert labels[0]["label"] == "needs-review"


def test_learner_recent_sessions_are_scoped_to_actor_cookie(tmp_path):
    qa_result = QAResult(
        question="Explain question 3.",
        short_answer="Question 3 uses a loop to visit one item at a time. [S1]",
        more_detail="The answer stays tied to local evidence.",
        unsure=False,
        result_mode="answered",
    )
    client, settings = _build_client(tmp_path, qa_result=qa_result)
    _insert_document(settings.db_path)

    save_qa_history(
        settings.db_path,
        question="Teacher-visible answer",
        retrieved_chunk_ids=[],
        answer_text="Teacher answer",
        more_detail="",
        unsure=False,
        result_mode="answered",
        actor_role="learner",
        actor_key="user-other1",
        class_space=settings.class_space,
        citation_list=[],
    )
    save_qa_history(
        settings.db_path,
        question="Current learner answer",
        retrieved_chunk_ids=[],
        answer_text="Current answer",
        more_detail="",
        unsure=False,
        result_mode="answered",
        actor_role="learner",
        actor_key="user-self1",
        class_space=settings.class_space,
        citation_list=[],
    )
    client.cookies.set("accesslab_actor", "user-self1")

    response = client.get("/")

    assert response.status_code == 200
    assert "Current learner answer" in response.text
    assert "Teacher-visible answer" not in response.text


def test_teacher_home_shows_recent_work(tmp_path):
    client, settings = _build_client(tmp_path)
    client.cookies.set("accesslab_role", "teacher")

    save_qa_history(
        settings.db_path,
        question="Explain loops",
        retrieved_chunk_ids=[],
        answer_text="Loops answer",
        more_detail="",
        unsure=False,
        result_mode="answered",
        actor_role="learner",
        actor_key="user-a123",
        class_space=settings.class_space,
        citation_list=[],
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "Recent learning activity" in response.text
    assert "Explain loops" in response.text


def test_learner_cannot_open_other_learners_saved_qa_session(tmp_path):
    client, settings = _build_client(tmp_path)
    _insert_document(settings.db_path)
    hidden_id = save_qa_history(
        settings.db_path,
        question="Other learner answer",
        retrieved_chunk_ids=[],
        answer_text="Hidden answer",
        more_detail="",
        unsure=False,
        result_mode="answered",
        actor_role="learner",
        actor_key="user-other1",
        class_space=settings.class_space,
        citation_list=[],
    )
    client.cookies.set("accesslab_actor", "user-self1")

    response = client.get(f"/qa?qa_id={hidden_id}")

    assert response.status_code == 404
    assert "Saved answer not found" in response.text
    assert "local role and class-space context" in response.text


def test_teacher_can_open_saved_learner_qa_session(tmp_path):
    client, settings = _build_client(tmp_path)
    _insert_document(settings.db_path)
    qa_id = save_qa_history(
        settings.db_path,
        question="Learner answer",
        retrieved_chunk_ids=[],
        answer_text="Teacher can inspect this",
        more_detail="",
        unsure=False,
        result_mode="answered",
        actor_role="learner",
        actor_key="user-other1",
        class_space=settings.class_space,
        citation_list=[],
    )
    client.cookies.set("accesslab_role", "teacher")

    response = client.get(f"/qa?qa_id={qa_id}")

    assert response.status_code == 200
    assert "Saved answer reopened" in response.text
    assert "Teacher can inspect this" in response.text


def test_learner_cannot_open_other_learners_saved_code_session(tmp_path):
    client, settings = _build_client(tmp_path)
    hidden_id = save_code_session(
        settings.db_path,
        original_code="print('hidden')\n",
        test_code="",
        execution_output="hidden",
        patched_code="print('hidden')\n",
        patched_test_result="hidden",
        actor_role="learner",
        actor_key="user-other1",
        class_space=settings.class_space,
    )
    client.cookies.set("accesslab_actor", "user-self1")

    response = client.get(f"/code?session_id={hidden_id}")

    assert response.status_code == 404
    assert "Saved code review not found" in response.text
    assert "local role and class-space context" in response.text
