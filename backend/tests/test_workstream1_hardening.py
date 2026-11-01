import pytest
from pydantic import ValidationError

from app.models import ActionDraft
from app.services.analysis_service import (
    _quote_exists,
    _frequency_consistency_warnings,
    _numeric_claim_warnings,
)
from app.services.diff_service import build_deterministic_diff


def test_quote_check_accepts_pdf_punctuation_and_unicode_variants():
    pages = [{
        "page": 2,
        "text": "All units shall be mandatorily registered under Udyam Portal.",
    }]

    assert _quote_exists(
        pages,
        2,
        "ALL units shall be mandatorily registered under Udyam Portal",
    )


def test_quote_check_rejects_missing_or_reordered_words():
    pages = [{
        "page": 1,
        "text": "Applicants must promptly submit the application form.",
    }]

    assert not _quote_exists(
        pages, 1, "Applicants must submit the application form"
    )
    assert not _quote_exists(
        pages, 1, "submit must Applicants promptly"
    )


def test_quote_check_rejects_invalid_page():
    pages = [{"page": 1, "text": "Applicants must submit the form."}]
    assert not _quote_exists(pages, 0, "Applicants must submit the form.")
    assert not _quote_exists(pages, 2, "Applicants must submit the form.")


def test_action_source_schema_rejects_filename_as_source_role():
    with pytest.raises(ValidationError):
        ActionDraft(
            action="Review the change",
            reason="The provision changed.",
            source_document="PMEGP Revised Guidelines Page 5",
            source_page=5,
            review_required=False,
        )


def test_action_source_schema_accepts_valid_role():
    action = ActionDraft(
        action="Review the revised provision",
        reason="The requirement changed.",
        source_document="later",
        source_page=5,
        review_required=False,
    )
    assert action.source_document == "later"


def test_quarterly_is_four_not_three():
    source = "Reports must be submitted quarterly."
    explanation = "Reports must be submitted three times per year."

    warnings = _frequency_consistency_warnings(source, explanation)
    assert warnings


def test_quarterly_four_times_per_year_is_consistent():
    source = "Reports must be submitted quarterly."
    explanation = "Reports must be submitted four times per year."

    assert not _frequency_consistency_warnings(source, explanation)


def test_unsupported_numeric_claim_is_flagged():
    source = "The eligible project cost is INR 200000."
    claim = "The eligible project cost is INR 250000."

    assert _numeric_claim_warnings(source, claim)


def test_equivalent_lakh_and_numeric_formats_are_supported():
    source = "The project cost is INR 2,00,000."
    claim = "The project cost is INR 2 lakh."

    assert not _numeric_claim_warnings(source, claim)


def test_candidate_counts_include_candidates_beyond_storage_cap():
    old_pages = [{
        "page": 1,
        "text": (
            "Applicants must submit annual reports to the authority. "
            "The authority shall verify each application carefully. "
            "The approved amount must be transferred to the account. "
            "The applicant must complete training before the deadline."
        ),
    }]

    new_pages = [{
        "page": 1,
        "text": (
            "Applicants must submit quarterly reports to the authority. "
            "The authority shall inspect each application carefully. "
            "The revised amount must be transferred to the account. "
            "The applicant must complete training after the deadline."
        ),
    }]

    diff = build_deterministic_diff(
        old_pages,
        new_pages,
        max_candidates=1,
    )

    assert diff["candidate_count"] == 1
    assert diff["total_candidate_count"] >= 1
    assert diff["candidates_truncated"] == (
        diff["total_candidate_count"] > 1
    )
    assert (
        diff["added_candidate_count"]
        + diff["removed_candidate_count"]
        + diff["modified_candidate_count"]
    ) == diff["total_candidate_count"]
