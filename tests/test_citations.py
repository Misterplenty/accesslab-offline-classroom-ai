from app.models.schemas import Citation, SearchResult
from app.services.qa import build_citations, parse_qa_response


def test_build_citations_formats_page_information():
    results = [
        SearchResult(
            chunk_id="worksheet-p2-c1",
            source_file="worksheet.pdf",
            page_number=2,
            chunk_text="Question 3 says the loop checks each value one by one.",
            snippet="Question 3 says the loop checks each value one by one.",
            score=0.1,
        )
    ]

    citations = build_citations(results)

    assert citations[0].label == "S1"
    assert citations[0].display == "[S1] worksheet.pdf, page 2 · worksheet-p2-c1"


def test_parse_qa_response_keeps_grouped_citations_without_duplication():
    citations = [
        Citation(
            label="S1",
            source_file="worksheet.md",
            page_number=None,
            chunk_id="worksheet-p0-c1",
            snippet="Loop explanation",
        ),
        Citation(
            label="S2",
            source_file="notes.pdf",
            page_number=1,
            chunk_id="notes-p1-c1",
            snippet="Loop note",
        ),
    ]

    short_answer, more_detail = parse_qa_response(
        "<short_answer>It checks each item one by one [S1, S2].</short_answer>"
        "<more_detail>Extra detail.</more_detail>",
        citations,
    )

    assert short_answer == "It checks each item one by one [S1, S2]."
    assert more_detail == "Extra detail."
