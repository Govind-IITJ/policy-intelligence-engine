from app.services.analysis_service import (
    _neutralize_repaired_pair_explanation,
    _same_policy_fact_restatement,
    _suppress_non_material_and_duplicate_findings,
)


def _change(change_id, title, old, new, explanation="candidate change"):
    return {
        "change_id": change_id,
        "title": title,
        "change_type": "modified" if old and new else ("added" if new else "removed"),
        "old_text": old,
        "old_quote": old,
        "new_text": new,
        "new_quote": new,
        "old_page": 1 if old else None,
        "new_page": 1 if new else None,
        "explanation": explanation,
        "review_required": True,
        "confidence": "low",
    }


def test_same_four_month_installment_frequency_is_not_reported_as_change():
    item = _change(
        "CHG-001",
        "Installment frequency changed",
        "benefit payable in three equal installments, every four months.",
        "farmers in three installments of Rs.2000/- each every 4-month / trimester.",
    )
    assert _same_policy_fact_restatement(item) == "same_four_month_installment_frequency_in_both_versions"


def test_same_eligibility_cutoff_date_is_not_reported_as_change():
    item = _change(
        "CHG-005",
        "Eligibility cutoff date changed",
        "01.02.2019 and no changes thereafter shall be considered for eligibility of benefit.",
        "shall be 01.02.2019 and no changes thereafter shall be considered for eligibility.",
    )
    assert _same_policy_fact_restatement(item) == "same_eligibility_cutoff_and_freeze_date_in_both_versions"


def test_same_direct_bank_transfer_mechanism_is_not_reported_as_change():
    item = _change(
        "CHG-002",
        "DBT mechanism changed",
        "amount is to be paid directly into their bank account through the mechanism of Direct Benefit Transfer DBT.",
        "amount is paid online directly into the bank accounts of the eligible farmers under Direct Benefit.",
    )
    assert _same_policy_fact_restatement(item) == "same_direct_bank_account_payment_mechanism_in_both_versions"


def test_same_annual_amount_restatement_is_not_a_substantive_change():
    item = _change(
        "CHG-009",
        "Annual amount changed",
        "benefit of Rs.6000 per annum per family payable in three equal installments.",
        "financial benefit of Rs.6000 per year is to be released to eligible farmers.",
    )
    assert _same_policy_fact_restatement(item) == "same_annual_benefit_amount_restated_in_both_versions"


def test_duplicate_payment_duplication_findings_are_consolidated_even_if_first_is_suppressed():
    first = _change(
        "CHG-008",
        "Clarification on non-duplication of payments",
        "States/UTs shall ensure that there is no duplication of the payment transferred to eligible families.",
        "shall ensure that there is no duplication of the payment transferred to eligible families.",
    )
    second = _change(
        "CHG-010",
        "Potential addition of payment duplication clause",
        "shall ensure that there is no duplication of the payment transferred to eligible families.",
        "duplication of the payment transferred to eligible families.",
    )
    kept, suppressed = _suppress_non_material_and_duplicate_findings([first, second])
    assert len(kept) == 0
    assert len(suppressed) == 2
    assert suppressed[1]["reason"] == "duplicate_or_overlapping_finding"
    assert suppressed[1]["duplicate_of"] == "CHG-008"


def test_contextless_fragment_is_suppressed_not_promoted_to_finding():
    item = _change("CHG-012", "Eligibility timeline modification", "", "during the year.")
    kept, suppressed = _suppress_non_material_and_duplicate_findings([item])
    assert kept == []
    assert suppressed[0]["reason"] == "incomplete_fragment_insufficient_context"


def test_distinct_succession_clause_is_retained_for_human_review():
    item = _change(
        "CHG-003",
        "Transfer/succession eligibility",
        "Benefit will be allowed where transfer of ownership takes place on account of succession due to death of the landowner.",
        "Transferees are not entitled for any benefits under PM-KISAN in such cases.",
    )
    kept, suppressed = _suppress_non_material_and_duplicate_findings([item])
    assert len(kept) == 1
    assert suppressed == []


def test_repaired_pair_replaces_stale_ai_rationale():
    item = _change(
        "CHG-003",
        "Old cutoff date changed",
        "transfer of ownership takes place on account of succession due to death of the landowner.",
        "Transferees are not entitled for any benefits in such cases.",
        explanation="The earlier text establishes an eligibility cut-off date.",
    )
    _neutralize_repaired_pair_explanation(item)
    assert "eligibility cut-off date" not in item["explanation"]
    assert "Earlier text:" in item["explanation"]
    assert item["review_required"] is True
    assert item["confidence"] == "low"
