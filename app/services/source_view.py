from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from markupsafe import Markup, escape

from app.db import db_connection


_TEXT_CONTEXT_CHARS = 280


@dataclass(slots=True)
class SourceContextChunk:
    chunk_id: str
    chunk_text: str
    is_cited: bool = False


@dataclass(slots=True)
class SourceView:
    document_id: int
    file_name: str
    file_type: str
    stored_path: str
    chunk_id: str
    page_number: int | None
    cited_snippet: str
    raw_file_href: str | None
    raw_file_label: str
    notice: str | None = None
    page_chunks: list[SourceContextChunk] = field(default_factory=list)
    excerpt_html: Markup = field(default_factory=lambda: Markup(""))

    @property
    def file_type_label(self) -> str:
        return self.file_type.upper()

    @property
    def page_label(self) -> str | None:
        if self.page_number is None:
            return None
        return f"Page {self.page_number}"

    @property
    def is_pdf(self) -> bool:
        return self.file_type == "pdf"


def build_document_file_href(document_id: int, file_type: str, page_number: int | None) -> str:
    href = f"/documents/{document_id}/file"
    if file_type == "pdf" and page_number is not None:
        return f"{href}#page={page_number}"
    return href


def load_source_view(
    db_path: Path,
    chunk_id: str,
    *,
    class_space: str | None = None,
) -> SourceView | None:
    with db_connection(db_path) as connection:
        params: list[object] = [chunk_id]
        class_space_filter = ""
        if class_space:
            class_space_filter = " AND d.class_space = ?"
            params.append(class_space)
        row = connection.execute(
            f"""
            SELECT
                d.id AS document_id,
                d.file_name,
                d.file_type,
                d.stored_path,
                c.chunk_id,
                c.page_number,
                c.chunk_text
            FROM document_chunks AS c
            JOIN documents AS d ON d.id = c.document_id
            WHERE c.chunk_id = ?{class_space_filter}
            LIMIT 1
            """,
            params,
        ).fetchone()
        if row is None:
            return None

        stored_path = Path(row["stored_path"])
        raw_file_href = None
        if stored_path.exists():
            raw_file_href = build_document_file_href(
                int(row["document_id"]),
                row["file_type"],
                row["page_number"],
            )

        view = SourceView(
            document_id=int(row["document_id"]),
            file_name=row["file_name"],
            file_type=row["file_type"],
            stored_path=row["stored_path"],
            chunk_id=row["chunk_id"],
            page_number=row["page_number"],
            cited_snippet=row["chunk_text"],
            raw_file_href=raw_file_href,
            raw_file_label="Open original PDF" if row["file_type"] == "pdf" else "Open raw file",
        )

        if view.is_pdf:
            page_rows = _load_pdf_page_rows(
                connection=connection,
                document_id=view.document_id,
                page_number=view.page_number,
                chunk_id=view.chunk_id,
                chunk_text=view.cited_snippet,
            )
            view.page_chunks = page_rows
            if not raw_file_href:
                view.notice = (
                    "The original PDF file is unavailable, so AccessLab is showing the indexed "
                    "page text only."
                )
            return view

    excerpt_html, notice = _build_text_excerpt(Path(view.stored_path), view.cited_snippet)
    if view.raw_file_href is None:
        unavailable = (
            "The original local file is unavailable, so AccessLab is showing the indexed "
            "evidence text only."
        )
        notice = f"{unavailable} {notice}".strip() if notice else unavailable
    view.excerpt_html = excerpt_html
    view.notice = notice
    return view


def _load_pdf_page_rows(
    *,
    connection,
    document_id: int,
    page_number: int | None,
    chunk_id: str,
    chunk_text: str,
) -> list[SourceContextChunk]:
    if page_number is None:
        return [SourceContextChunk(chunk_id=chunk_id, chunk_text=chunk_text, is_cited=True)]

    rows = connection.execute(
        """
        SELECT chunk_id, chunk_text
        FROM document_chunks
        WHERE document_id = ? AND page_number = ?
        ORDER BY id
        """,
        (document_id, page_number),
    ).fetchall()
    if not rows:
        return [SourceContextChunk(chunk_id=chunk_id, chunk_text=chunk_text, is_cited=True)]

    return [
        SourceContextChunk(
            chunk_id=row["chunk_id"],
            chunk_text=row["chunk_text"],
            is_cited=row["chunk_id"] == chunk_id,
        )
        for row in rows
    ]


def _build_text_excerpt(file_path: Path, chunk_text: str) -> tuple[Markup, str | None]:
    if not file_path.exists():
        return _fallback_excerpt_markup(chunk_text), None

    try:
        raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return (
            _fallback_excerpt_markup(chunk_text),
            f"AccessLab could not read the stored file ({exc}); showing the indexed evidence excerpt instead.",
        )

    match_span = _locate_chunk_span(raw_text, chunk_text)
    if match_span is None:
        return (
            _fallback_excerpt_markup(chunk_text),
            "AccessLab could not re-locate the exact cited excerpt inside the stored file, so this view "
            "shows the indexed evidence text.",
        )

    start, end = match_span
    excerpt_start = max(0, start - _TEXT_CONTEXT_CHARS)
    excerpt_end = min(len(raw_text), end + _TEXT_CONTEXT_CHARS)
    before = raw_text[excerpt_start:start]
    highlight = raw_text[start:end]
    after = raw_text[end:excerpt_end]

    parts: list[str] = []
    if excerpt_start > 0:
        parts.append('<span class="source-excerpt__ellipsis" aria-hidden="true">…</span>')
    parts.append(str(escape(before)))
    parts.append(f"<mark>{escape(highlight)}</mark>")
    parts.append(str(escape(after)))
    if excerpt_end < len(raw_text):
        parts.append('<span class="source-excerpt__ellipsis" aria-hidden="true">…</span>')
    return Markup("".join(parts)), None


def _locate_chunk_span(raw_text: str, chunk_text: str) -> tuple[int, int] | None:
    candidates = [chunk_text.strip()]
    shortened = chunk_text.strip()[:160].strip()
    if shortened and shortened not in candidates:
        candidates.append(shortened)

    sentence_match = re.match(r"(.+?[.!?])(?:\s|$)", chunk_text.strip())
    if sentence_match:
        sentence = sentence_match.group(1).strip()
        if sentence and sentence not in candidates:
            candidates.append(sentence)

    for candidate in candidates:
        span = _find_flexible_span(raw_text, candidate)
        if span is not None:
            return span
    return None


def _find_flexible_span(raw_text: str, needle: str) -> tuple[int, int] | None:
    tokens = [token for token in needle.split() if token]
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    for flags in (0, re.IGNORECASE):
        match = re.search(pattern, raw_text, flags=flags)
        if match is not None:
            return match.span()
    return None


def _fallback_excerpt_markup(chunk_text: str) -> Markup:
    return Markup(f"<mark>{escape(chunk_text)}</mark>")
