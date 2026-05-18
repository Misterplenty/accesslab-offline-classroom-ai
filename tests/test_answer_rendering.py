from app.models.schemas import Citation
from app.services import answer_rendering


def _citations() -> list[Citation]:
    return [
        Citation(
            label="S1",
            source_file="algebra_notes.md",
            page_number=2,
            chunk_id="teacher-p2-c1",
            snippet="The formula for a rectangle's area is A = l x w.",
        ),
        Citation(
            label="S2",
            source_file="worksheet.pdf",
            page_number=None,
            chunk_id="worksheet-section-4",
            snippet="Question 4 asks for the area using the same formula.",
        ),
    ]


def test_build_evidence_cards_generates_deterministic_anchor_ids():
    cards = answer_rendering.build_evidence_cards(_citations())

    assert [card.anchor_id for card in cards] == [
        "evidence-teacher-p2-c1-s1",
        "evidence-worksheet-section-4-s2",
    ]
    assert [card.source_href for card in cards] == [
        "/sources/teacher-p2-c1",
        "/sources/worksheet-section-4",
    ]


def test_build_evidence_cards_carries_qa_id_into_source_links():
    cards = answer_rendering.build_evidence_cards(_citations(), qa_id=12)

    assert [card.source_href for card in cards] == [
        "/sources/teacher-p2-c1?qa_id=12",
        "/sources/worksheet-section-4?qa_id=12",
    ]


def test_render_answer_html_escapes_plain_html_and_links_known_citations():
    html = str(
        answer_rendering.render_answer_html(
            "Use <script>alert(1)</script> carefully [S1, S2].",
            _citations(),
        )
    )

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'href="#evidence-teacher-p2-c1-s1"' in html
    assert 'href="#evidence-worksheet-section-4-s2"' in html
    assert html.count('class="citation-link"') == 2


def test_render_answer_html_renders_inline_and_display_math():
    html = str(
        answer_rendering.render_answer_html(
            "The area can be written as $A = l \\\\times w$.\n\n$$\\\\frac{a}{b}$$",
            _citations(),
        )
    )

    assert html.count("<math ") == 2
    assert 'data-tex-source="$A = l \\\\times w$"' in html
    assert 'data-tex-source="$$\\\\frac{a}{b}$$"' in html
    assert 'class="math-fragment math-fragment--block"' in html


def test_render_answer_html_falls_back_to_readable_tex_when_math_renderer_is_unavailable(monkeypatch):
    monkeypatch.setattr(answer_rendering, "latex_to_mathml", None)

    html = str(answer_rendering.render_answer_html("Use $x^2$ here.", _citations()))

    assert "<math " not in html
    assert "$x^2$" in html
    assert 'class="math-fallback"' in html


def test_render_answer_html_keeps_code_blocks_literal():
    html = str(
        answer_rendering.render_answer_html(
            "```python\nprint('[S1] $x^2$')\n```",
            _citations(),
        )
    )

    assert '<pre class="answer-code"><code>' in html
    assert "[S1] $x^2$" in html
    assert 'class="citation-link"' not in html
    assert "<math " not in html
