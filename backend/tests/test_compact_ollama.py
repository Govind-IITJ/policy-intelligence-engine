from app.services.ai_service import (
    _assemble_comparison_draft,
    _parse_compact_response,
)


def make_docs():
    earlier = {
        "document_id": "old",
        "filename": "old.pdf",
        "title": "Earlier Policy",
        "page_count": 5,
        "pages": [],
        "empty_pages": [],
    }
    later = {
        "document_id": "new",
        "filename": "new.pdf",
        "title": "Later Policy",
        "page_count": 6,
        "pages": [],
        "empty_pages": [],
    }
    return earlier, later


def test_compact_json_parser_accepts_small_valid_response():
    raw = (
        '{"findings":[{'
        '"candidate_id":"C01",'
        '"title":"Udyam registration requirement",'
        '"change_type":"document_requirement",'
        '"explanation":"Registration is required in the later provision.",'
        '"affected_stakeholders":["PMEGP applicants"],'
        '"practical_action":"Complete the required registration.",'
        '"confidence":"medium",'
        '"review_required":true'
        '}]}'
    )

    findings = _parse_compact_response(raw)
    assert len(findings) == 1
    assert findings[0]["candidate_id"] == "C01"


def test_compact_parser_rejects_truncated_json():
    raw = '{"findings":[{"candidate_id":"C01","title":"unfinished'
    try:
        _parse_compact_response(raw)
    except RuntimeError:
        return
    raise AssertionError("Truncated JSON was accepted.")


def test_backend_attaches_exact_source_pages_and_quotes():
    earlier, later = make_docs()

    selected = [{
        "operation": "modified",
        "old_page": 7,
        "old_text": "Udyam registration was encouraged for PMEGP units.",
        "new_page": 3,
        "new_text": "Udyam registration is mandatory for PMEGP units.",
        "alignment_similarity": 0.72,
    }]

    findings = [{
        "candidate_id": "C01",
        "title": "Udyam registration requirement",
        "change_type": "document_requirement",
        "explanation": "The later provision makes registration mandatory.",
        "affected_stakeholders": ["PMEGP applicants"],
        "practical_action": "Complete Udyam registration.",
        "confidence": "medium",
        "review_required": True,
    }]

    draft = _assemble_comparison_draft(
        earlier, later, selected, findings, 1, False
    )

    change = draft.changes[0]
    assert change.old_page == 7
    assert change.new_page == 3
    assert change.old_quote == selected[0]["old_text"]
    assert change.new_quote == selected[0]["new_text"]
    assert change.change_type == "document_requirement"
    assert draft.action_checklist[0].source_document == "later"
    assert draft.action_checklist[0].source_page == 3


def test_added_candidate_gets_no_fabricated_earlier_evidence():
    earlier, later = make_docs()

    selected = [{
        "operation": "added",
        "old_page": None,
        "old_text": "",
        "new_page": 4,
        "new_text": "Applicants must register before the claim is processed.",
        "alignment_similarity": None,
    }]

    findings = [{
        "candidate_id": "C01",
        "title": "New registration requirement",
        "change_type": "document_requirement",
        "explanation": "A new registration requirement appears.",
        "affected_stakeholders": ["Applicants"],
        "practical_action": "Review the registration requirement.",
        "confidence": "medium",
        "review_required": True,
    }]

    draft = _assemble_comparison_draft(
        earlier, later, selected, findings, 1, False
    )

    change = draft.changes[0]
    assert change.change_type == "added"
    assert change.old_page is None
    assert change.old_quote == ""
    assert change.new_page == 4


def test_unknown_candidate_id_is_not_given_source_evidence():
    earlier, later = make_docs()

    selected = [{
        "operation": "added",
        "old_page": None,
        "old_text": "",
        "new_page": 4,
        "new_text": "Applicants must register before the claim is processed.",
        "alignment_similarity": None,
    }]

    findings = [{
        "candidate_id": "C99",
        "title": "Invented finding",
        "change_type": "added",
        "explanation": "Unknown candidate.",
        "affected_stakeholders": [],
        "practical_action": "Take action.",
        "confidence": "high",
        "review_required": False,
    }]

    draft = _assemble_comparison_draft(
        earlier, later, selected, findings, 1, False
    )

    assert len(draft.changes) == 0
    assert draft.overall_review_required is True
    assert any("unknown candidate" in item for item in draft.limitations)
