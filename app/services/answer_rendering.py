from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

from markupsafe import Markup, escape

from app.models.schemas import Citation

try:  # pragma: no cover - exercised indirectly when dependency is absent
    from latex2mathml.converter import convert as latex_to_mathml
except ImportError:  # pragma: no cover - dependency fallback
    latex_to_mathml = None


_CITATION_GROUP_PATTERN = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*)\]")
_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
_MATHML_NAMESPACE = "{http://www.w3.org/1998/Math/MathML}"


@dataclass(slots=True)
class EvidenceCard:
    label: str
    anchor_id: str
    source_file: str
    page_number: int | None
    chunk_id: str
    snippet: str
    source_href: str

    @property
    def page_label(self) -> str | None:
        if self.page_number is None:
            return None
        return f"Page {self.page_number}"

    @property
    def chunk_label(self) -> str:
        return self.chunk_id

    @property
    def jump_label(self) -> str:
        if self.page_number is None:
            return f"Jump to evidence {self.label} from {self.source_file}"
        return f"Jump to evidence {self.label} from {self.source_file}, page {self.page_number}"

    @property
    def source_view_label(self) -> str:
        if self.page_number is None:
            return f"Open source view for {self.source_file}, evidence reference {self.chunk_id}"
        return (
            f"Open source view for {self.source_file}, page {self.page_number}, "
            f"evidence reference {self.chunk_id}"
        )


def build_evidence_cards(
    citations: list[Citation],
    qa_id: int | None = None,
) -> list[EvidenceCard]:
    return [
        EvidenceCard(
            label=citation.label,
            anchor_id=build_evidence_anchor_id(citation),
            source_file=citation.source_file,
            page_number=citation.page_number,
            chunk_id=citation.chunk_id,
            snippet=citation.snippet,
            source_href=build_source_view_href(citation.chunk_id, qa_id=qa_id),
        )
        for citation in citations
    ]


def build_evidence_anchor_id(citation: Citation) -> str:
    slug = _NON_ALNUM_PATTERN.sub("-", citation.chunk_id.lower()).strip("-")
    if not slug:
        slug = citation.label.lower()
    return f"evidence-{slug}-{citation.label.lower()}"


def build_source_view_href(chunk_id: str, qa_id: int | None = None) -> str:
    href = f"/sources/{quote(chunk_id, safe='')}"
    if qa_id is None:
        return href
    return f"{href}?{urlencode({'qa_id': qa_id})}"


def render_answer_html(text: str, citations: list[Citation]) -> Markup:
    if not text.strip():
        return Markup("")

    cards = build_evidence_cards(citations)
    citation_lookup = {card.label: card for card in cards}
    rendered_blocks: list[str] = []
    for block_type, content in _split_blocks(text):
        if block_type == "paragraph":
            rendered_blocks.append(f"<p>{_render_inline_text(content, citation_lookup)}</p>")
            continue
        if block_type == "code":
            rendered_blocks.append(
                f'<pre class="answer-code"><code>{escape(content)}</code></pre>'
            )
            continue
        rendered_blocks.append(_render_math_fragment(content, display="block"))
    return Markup("\n".join(rendered_blocks))


def _split_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        paragraph = " ".join(line.strip() for line in paragraph_lines if line.strip()).strip()
        paragraph_lines.clear()
        if paragraph:
            blocks.append(("paragraph", paragraph))

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(("code", "\n".join(code_lines).strip("\n")))
            continue

        if stripped in ("$$", "\\["):
            closing = "$$" if stripped == "$$" else "\\]"
            math_lines: list[str] = []
            probe = index + 1
            while probe < len(lines) and lines[probe].strip() != closing:
                math_lines.append(lines[probe])
                probe += 1
            if probe < len(lines):
                flush_paragraph()
                formula = "\n".join(math_lines).strip()
                if formula:
                    blocks.append(("display_math", formula))
                index = probe + 1
                continue

        standalone_formula = _extract_standalone_display_math(stripped)
        if standalone_formula is not None:
            flush_paragraph()
            blocks.append(("display_math", standalone_formula))
            index += 1
            continue

        paragraph_lines.append(line)
        index += 1

    flush_paragraph()
    return blocks


def _extract_standalone_display_math(text: str) -> str | None:
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        return text[2:-2].strip()
    if text.startswith("\\[") and text.endswith("\\]") and len(text) > 4:
        return text[2:-2].strip()
    return None


def _render_inline_text(text: str, citation_lookup: dict[str, EvidenceCard]) -> Markup:
    parts: list[str] = []
    plain_text: list[str] = []
    index = 0

    def flush_plain_text() -> None:
        if plain_text:
            parts.append(str(escape("".join(plain_text))))
            plain_text.clear()

    while index < len(text):
        citation_match = _CITATION_GROUP_PATTERN.match(text, index)
        if citation_match:
            labels = [label.strip() for label in citation_match.group(1).split(",")]
            if all(label in citation_lookup for label in labels):
                flush_plain_text()
                parts.append(_render_citation_group(labels, citation_lookup))
                index = citation_match.end()
                continue

        if text[index] == "`":
            closing = text.find("`", index + 1)
            if closing != -1:
                flush_plain_text()
                parts.append(f"<code>{escape(text[index + 1:closing])}</code>")
                index = closing + 1
                continue

        inline_math = _extract_inline_math(text, index)
        if inline_math is not None:
            source_text, latex, next_index = inline_math
            flush_plain_text()
            parts.append(_render_math_fragment(latex, display="inline", source_text=source_text))
            index = next_index
            continue

        plain_text.append(text[index])
        index += 1

    flush_plain_text()
    return Markup("".join(parts))


def _extract_inline_math(text: str, index: int) -> tuple[str, str, int] | None:
    if text.startswith("\\(", index):
        closing = text.find("\\)", index + 2)
        if closing != -1:
            latex = text[index + 2:closing].strip()
            if latex:
                return text[index:closing + 2], latex, closing + 2

    if text.startswith("$$", index):
        closing = text.find("$$", index + 2)
        if closing != -1:
            latex = text[index + 2:closing].strip()
            if latex:
                return text[index:closing + 2], latex, closing + 2

    if text[index] == "$" and not text.startswith("$$", index):
        closing = _find_unescaped_dollar(text, index + 1)
        if closing != -1:
            latex = text[index + 1:closing].strip()
            if latex:
                return text[index:closing + 1], latex, closing + 1

    return None


def _find_unescaped_dollar(text: str, start: int) -> int:
    probe = start
    while probe < len(text):
        if text[probe] == "$" and text[probe - 1] != "\\":
            return probe
        probe += 1
    return -1


def _render_citation_group(labels: list[str], citation_lookup: dict[str, EvidenceCard]) -> str:
    links: list[str] = []
    for position, label in enumerate(labels):
        card = citation_lookup[label]
        links.append(
            (
                f'<a class="citation-link" href="#{escape(card.anchor_id)}" '
                f'data-evidence-target="{escape(card.anchor_id)}" '
                f'aria-label="{escape(card.jump_label)}">[{escape(label)}]</a>'
            )
        )
        if position < len(labels) - 1:
            links.append(", ")
    return f'<span class="citation-group">{"".join(links)}</span>'


def _render_math_fragment(latex: str, *, display: str, source_text: str | None = None) -> str:
    raw_source = source_text or _wrap_math_source(latex, display)
    fallback = f'<code class="math-fallback">{escape(raw_source)}</code>'
    wrapper = "div" if display == "block" else "span"
    if latex_to_mathml is None:
        return (
            f'<{wrapper} class="math-fragment math-fragment--{display}" '
            f'data-tex-source="{escape(raw_source)}">{fallback}</{wrapper}>'
        )

    try:
        mathml = latex_to_mathml(latex, display=display)
        root = ElementTree.fromstring(mathml)
        if not str(root.tag).startswith(_MATHML_NAMESPACE):
            raise ValueError("unexpected mathml namespace")
        for node in root.iter():
            if not str(node.tag).startswith(_MATHML_NAMESPACE):
                raise ValueError("unexpected tag in mathml output")
        safe_mathml = mathml
    except Exception:
        return (
            f'<{wrapper} class="math-fragment math-fragment--{display}" '
            f'data-tex-source="{escape(raw_source)}">{fallback}</{wrapper}>'
        )

    return (
        f'<{wrapper} class="math-fragment math-fragment--{display}" '
        f'data-tex-source="{escape(raw_source)}">'
        f"{safe_mathml}"
        f"{fallback}"
        f"</{wrapper}>"
    )


def _wrap_math_source(latex: str, display: str) -> str:
    if display == "block":
        return f"$${latex}$$"
    return f"${latex}$"
