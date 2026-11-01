from app.services.diff_service import build_deterministic_diff


def pages(*values):
    return [{"page": index, "text": value} for index, value in enumerate(values, start=1)]


def test_detects_addition_removal_and_modification_with_page_references():
    earlier = pages(
        "Eligibility. Applicants must have annual family income below INR 200000. "
        "Applications close on 30 June 2025. The applicant must submit a signed paper form."
    )
    later = pages(
        "Eligibility. Applicants must have annual family income below INR 300000. "
        "Applications close on 15 July 2025. Applicants may submit the form online. "
        "A photograph is required."
    )

    result = build_deterministic_diff(earlier, later)
    operations = {item["operation"] for item in result["candidates"]}

    assert result["candidate_count"] >= 3
    assert "modified" in operations
    assert "added" in operations
    assert result["sequence_similarity"] < 1
    assert all(item["old_page"] == 1 for item in result["candidates"] if item["old_page"] is not None)
    assert all(item["new_page"] == 1 for item in result["candidates"] if item["new_page"] is not None)


def test_identical_documents_have_no_candidates():
    source = pages("The policy explains application eligibility and the submission deadline.")
    result = build_deterministic_diff(source, source)
    assert result["candidate_count"] == 0
    assert result["sequence_similarity"] == 1


def test_changed_page_is_preserved_in_candidate_evidence():
    earlier = pages("Common unchanged introduction with sufficient length for extraction.",
                    "Applicants must submit the form by 30 June 2025.")
    later = pages("Common unchanged introduction with sufficient length for extraction.",
                  "Applicants must submit the form by 31 July 2025.")
    result = build_deterministic_diff(earlier, later)
    changed = [item for item in result["candidates"] if item["operation"] == "modified"]
    assert changed
    assert changed[0]["old_page"] == 2
    assert changed[0]["new_page"] == 2


def test_candidate_cap_reports_truncation():
    earlier = pages("First sentence with enough length to be captured. Second sentence with enough length to be captured.")
    later = pages("New first sentence with different wording and enough length. New second sentence also has different wording.")
    result = build_deterministic_diff(earlier, later, max_candidates=1)
    assert result["candidate_count"] == 1
    assert result["total_candidate_count"] >= result["candidate_count"]
    assert result["candidates_truncated"] is (result["total_candidate_count"] > 1)
