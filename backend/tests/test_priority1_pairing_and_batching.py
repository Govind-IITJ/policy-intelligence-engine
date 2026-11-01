from app.config import settings
from app.services.ai_service import analyse_documents
from app.services.analysis_service import _reconcile_change_pairing


def _page(number, text):
    return {"page": number, "text": text}


def test_pm_kisan_inheritance_does_not_inherit_unrelated_cutoff_quote():
    earlier = [
        _page(
            3,
            "01.02.2019 and no changes thereafter shall be considered for eligibility of benefit under the scheme.",
        ),
        _page(
            7,
            "Eligible farmer families shall be identified from the land records maintained by the State.",
        ),
    ]
    later = [
        _page(
            5,
            "Transferees are not entitled for any benefits under PM-KISAN in such cases.",
        )
    ]
    change = {
        "title": "Exclusion of transferees from benefits under inheritance",
        "change_type": "eligibility",
        "old_page": 3,
        "old_text": "01.02.2019 and no changes thereafter shall be considered for eligibility of benefit under the",
        "old_quote": "01.02.2019 and no changes thereafter shall be considered for eligibility of benefit under the",
        "new_page": 5,
        "new_text": "Transferees are not entitled for any benefits under PM-KISAN in such cases.",
        "new_quote": "Transferees are not entitled for any benefits under PM-KISAN in such cases.",
        "explanation": "Added clause explicitly states that transferees are not entitled to benefits in inheritance cases.",
        "review_required": False,
        "confidence": "low",
    }

    result = _reconcile_change_pairing(change, earlier, later)

    assert result["change_type"] == "added"
    assert result["old_page"] is None
    assert result["old_quote"] == ""
    assert result["new_page"] == 5
    assert result["pairing_verification"]["pairing_verified"] is False
    assert result["pairing_verification"]["status"] == "unrelated_old_new_pair_rejected"
    assert result["addition_verification"]["confirmed_addition"] is False
    assert result["review_required"] is True
    assert "provisional addition candidate" in result["explanation"]


def test_modified_pairing_finds_same_subject_clause_on_different_earlier_page():
    earlier = [
        _page(3, "01.02.2019 and no changes thereafter shall be considered for eligibility."),
        _page(8, "Land acquired by transferees through inheritance shall not qualify for benefits under the scheme."),
    ]
    later = [
        _page(5, "Transferees are not entitled for any benefits under PM-KISAN in such cases.")
    ]
    change = {
        "title": "Inheritance-related transfer restriction",
        "change_type": "eligibility",
        "old_page": 3,
        "old_text": "01.02.2019 and no changes thereafter shall be considered for eligibility.",
        "old_quote": "01.02.2019 and no changes thereafter shall be considered for eligibility.",
        "new_page": 5,
        "new_text": "Transferees are not entitled for any benefits under PM-KISAN in such cases.",
        "new_quote": "Transferees are not entitled for any benefits under PM-KISAN in such cases.",
        "explanation": "The inheritance-related restriction appears in the later policy.",
        "review_required": False,
        "confidence": "medium",
    }

    result = _reconcile_change_pairing(change, earlier, later)

    assert result["old_page"] == 8
    assert "inheritance" in result["old_quote"].casefold()
    assert result["pairing_verification"]["status"] == "earlier_counterpart_repaired"
    assert result["pairing_verification"]["pairing_verified"] is True
    assert result["review_required"] is True


def test_added_candidate_is_reclassified_when_corresponding_clause_exists_earlier():
    earlier = [
        _page(2, "EDP training is mandatory for beneficiaries before the release of the loan.")
    ]
    later = [
        _page(4, "Beneficiaries must complete EDP training before loan release.")
    ]
    change = {
        "title": "EDP training requirement",
        "change_type": "added",
        "old_page": None,
        "old_text": "",
        "old_quote": "",
        "new_page": 4,
        "new_text": "Beneficiaries must complete EDP training before loan release.",
        "new_quote": "Beneficiaries must complete EDP training before loan release.",
        "explanation": "EDP training appears as a requirement.",
        "review_required": False,
        "confidence": "medium",
    }

    result = _reconcile_change_pairing(change, earlier, later)

    assert result["change_type"] == "modified"
    assert result["old_page"] == 2
    assert result["pairing_verification"]["status"] == "earlier_counterpart_found"
    assert result["review_required"] is True


def test_addition_without_counterpart_is_provisional_not_confirmed():
    earlier = [_page(1, "The scheme is administered by the designated State agencies.")]
    later = [_page(4, "All transferees acquiring land through inheritance are ineligible for this benefit.")]
    change = {
        "title": "Inheritance eligibility restriction",
        "change_type": "added",
        "old_page": None,
        "old_text": "",
        "old_quote": "",
        "new_page": 4,
        "new_text": "All transferees acquiring land through inheritance are ineligible for this benefit.",
        "new_quote": "All transferees acquiring land through inheritance are ineligible for this benefit.",
        "explanation": "A new inheritance restriction appears.",
        "review_required": False,
        "confidence": "high",
    }

    result = _reconcile_change_pairing(change, earlier, later)

    assert result["change_type"] == "added"
    assert result["addition_verification"]["confirmed_addition"] is False
    assert result["addition_verification"]["search_scope"] == "all_extracted_earlier_document_pages"
    assert result["review_required"] is True
    assert result["confidence"] == "low"


def test_full_document_search_can_locate_related_later_clause_for_removal():
    earlier_text = "100% physical verification with geo-tagging is mandatory for all beneficiary units."
    later = [
        _page(1, "Scheme overview and administration."),
        _page(9, "The actual establishment and working status of every beneficiary unit will be checked through 100% physical verification with geo-tagging."),
    ]
    change = {
        "title": "Removal of physical verification requirement",
        "change_type": "removed",
        "old_page": 4,
        "old_text": earlier_text,
        "old_quote": earlier_text,
        "new_page": None,
        "new_text": "",
        "new_quote": "",
        "explanation": "The earlier requirement was removed.",
        "review_required": False,
        "confidence": "medium",
    }

    result = _reconcile_change_pairing(change, [_page(4, earlier_text)], later)

    assert result["change_type"] == "modified"
    assert result["new_page"] == 9
    assert result["removal_verification"]["confirmed_repeal"] is False
    assert result["review_required"] is True


def test_ollama_candidate_review_is_batched_and_coverage_is_truthful(monkeypatch):
    candidates = []
    for index in range(35):
        candidates.append({
            "operation": "modified",
            "old_page": (index % 10) + 1,
            "old_text": f"Prior eligibility provision item {index} requires applicants to submit a signed district verification form.",
            "new_page": (index % 12) + 1,
            "new_text": f"Revised eligibility provision item {index} requires applicants to submit a digitally verified district application form.",
            "alignment_similarity": 0.68,
        })

    earlier = {
        "document_id": "earlier",
        "filename": "earlier.pdf",
        "title": "Earlier scheme",
        "page_count": 10,
        "pages": [_page(1, "Earlier scheme source document.")],
        "empty_pages": [],
    }
    later = {
        "document_id": "later",
        "filename": "later.pdf",
        "title": "Later scheme",
        "page_count": 12,
        "pages": [_page(1, "Later scheme source document.")],
        "empty_pages": [],
    }
    diff = {
        "candidates": candidates,
        "candidate_count": 35,
        "total_candidate_count": 35,
        "candidate_limit": 2500,
        "candidates_truncated": False,
        "old_unit_count": 35,
        "new_unit_count": 35,
        "sequence_similarity": 0.7,
        "exact_unit_sequence_ratio": 0.2,
        "added_candidate_count": 0,
        "removed_candidate_count": 0,
        "modified_candidate_count": 35,
        "earlier_characters": 1000,
        "later_characters": 1100,
    }

    monkeypatch.setattr(settings, "ai_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_candidate_review_limit", 35)
    monkeypatch.setattr(settings, "ollama_candidate_batch_size", 10)

    reviewed_ids = []
    def fake_ollama(content):
        import json
        payload = json.loads(content.split("\n\n", 1)[-1])
        ids = [item["candidate_id"] for item in payload["candidates"]]
        reviewed_ids.extend(ids)
        return []

    monkeypatch.setattr("app.services.ai_service._analyse_with_ollama", fake_ollama)

    from app.services.ai_service import analyse_documents
    draft = analyse_documents(earlier, later, diff)

    assert len(reviewed_ids) == 35
    assert len(set(reviewed_ids)) == 35
    assert reviewed_ids[0] == "C01"
    assert reviewed_ids[-1] == "C35"
    assert draft.candidate_review_metadata["batches_planned"] == 4
    assert draft.candidate_review_metadata["batches_succeeded"] == 4
    assert draft.candidate_review_metadata["reviewed_candidates"] == 35
    assert draft.candidate_review_metadata["detected_candidates"] == 35
    assert draft.candidate_review_metadata["selected_candidates"] == 35


def test_priority_selector_preserves_added_removed_and_modified_candidate_coverage():
    from app.services.ai_service import _select_candidates

    candidates = []
    for operation in ("modified", "added", "removed"):
        for index in range(24):
            candidates.append({
                "operation": operation,
                "old_page": index + 1 if operation != "added" else None,
                "old_text": (
                    f"Prior {operation} provision {index} requires applicants to complete annual verification."
                    if operation != "added" else ""
                ),
                "new_page": index + 1 if operation != "removed" else None,
                "new_text": (
                    f"Revised {operation} provision {index} requires applicants to complete digital verification."
                    if operation != "removed" else ""
                ),
            })

    selected = _select_candidates(candidates, limit=30)
    counts = {
        operation: sum(1 for candidate in selected if candidate["operation"] == operation)
        for operation in ("modified", "added", "removed")
    }

    assert len(selected) == 30
    assert counts == {"modified": 10, "added": 10, "removed": 10}


def test_unpaired_finding_downgrades_its_generated_action_to_review_task(tmp_path, monkeypatch):
    from app import database
    from app.config import settings as app_settings
    from app.models import ActionDraft, ChangeDraft, ComparisonDraft
    from app.services import analysis_service

    def make_doc(document_id, version, pages, sha):
        return {
            "document_id": document_id,
            "filename": f"{version}.pdf",
            "stored_path": f"{document_id}.pdf",
            "version": version,
            "title": "PM-KISAN test policy",
            "page_count": len(pages),
            "extracted_characters": sum(len(p["text"]) for p in pages),
            "pages": pages,
            "created_at": database.utc_now(),
            "sha256": sha,
            "file_size_bytes": 100,
            "nonempty_pages": len(pages),
            "empty_pages": [],
            "pdf_metadata": {},
            "warnings": [],
        }

    old_text = "01.02.2019 and no changes thereafter shall be considered for eligibility of benefit under the scheme."
    new_text = "Transferees are not entitled for any benefits under PM-KISAN in such cases."
    earlier_pages = [_page(1, "Intro."), _page(2, "Section heading."), _page(3, old_text)]
    later_pages = [
        _page(1, "Introduction."),
        _page(2, "Overview."),
        _page(3, "Definitions."),
        _page(4, "Eligibility section."),
        _page(5, new_text),
    ]
    earlier = make_doc("pair-old", "earlier", earlier_pages, "old-pair-hash")
    later = make_doc("pair-new", "later", later_pages, "new-pair-hash")

    monkeypatch.setattr(app_settings, "data_dir", str(tmp_path))
    database.init_db()
    database.insert_document(earlier)
    database.insert_document(later)

    original_explanation = "Added restriction stating that transferees are not entitled to benefits in inheritance cases."
    draft = ComparisonDraft(
        document_title="PM-KISAN test policy",
        executive_summary="A candidate inheritance-related eligibility change was detected.",
        key_findings=[original_explanation],
        changes=[
            ChangeDraft(
                title="Exclusion of transferees from benefits under inheritance",
                change_type="eligibility",
                old_text=old_text,
                new_text=new_text,
                explanation=original_explanation,
                affected_stakeholders=["Transferees"],
                practical_action="Exclude individuals who acquired land through inheritance from the beneficiary list.",
                old_page=3,
                old_quote=old_text,
                new_page=5,
                new_quote=new_text,
                confidence="low",
                review_required=False,
            )
        ],
        action_checklist=[
            ActionDraft(
                action="Exclude individuals who acquired land through inheritance from the beneficiary list.",
                reason=original_explanation,
                source_document="later",
                source_page=5,
                review_required=False,
            )
        ],
        limitations=[],
        overall_review_required=False,
    )
    monkeypatch.setattr(analysis_service, "analyse_documents", lambda *args: draft)

    database.insert_analysis("pairing-integrity-analysis", "pair-old", "pair-new")
    analysis_service.run_analysis_job("pairing-integrity-analysis", "pair-old", "pair-new")

    saved = database.get_analysis("pairing-integrity-analysis")
    assert saved["status"] == "completed"
    finding = saved["result"]["changes"][0]
    action = saved["result"]["action_checklist"][0]

    assert finding["old_page"] is None
    assert finding["pairing_verified"] is False
    assert finding["review_required"] is True
    assert finding["evidence_verified"] is True  # The later quote itself is correctly page-matched.
    assert "different subject" in finding["evidence_warning"].casefold()
    assert action["review_required"] is True
    assert "review" in action["action"].casefold()
    assert "exclude individuals" not in action["action"].casefold()



def test_manual_review_benchmark_pairs_from_pm_kisan_and_pmegp():
    import json
    from pathlib import Path
    from app.services.analysis_service import _provision_pair_score

    fixture_path = Path(__file__).parent / "fixtures" / "priority1_manual_pairing_cases.json"
    benchmark = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert len(benchmark["cases"]) == 4

    for case in benchmark["cases"]:
        score = _provision_pair_score(
            case["earlier_excerpt"],
            case["later_excerpt"],
        )
        assert score["compatible"] is case["expected_pairing_compatible"], case["id"]


def test_openai_provider_uses_same_compact_candidate_batches(monkeypatch):
    import json
    from app.services.ai_service import analyse_documents

    candidates = []
    for index in range(5):
        candidates.append({
            "operation": "modified",
            "old_page": index + 1,
            "new_page": index + 1,
            "old_text": f"Earlier rule {index} requires a signed paper verification form.",
            "new_text": f"Later rule {index} requires a digitally verified application form.",
            "alignment_similarity": 0.71,
        })
    earlier = {
        "document_id": "old", "filename": "old.pdf", "title": "Old policy",
        "page_count": 5, "pages": [_page(i + 1, c["old_text"]) for i, c in enumerate(candidates)],
        "empty_pages": [],
    }
    later = {
        "document_id": "new", "filename": "new.pdf", "title": "New policy",
        "page_count": 5, "pages": [_page(i + 1, c["new_text"]) for i, c in enumerate(candidates)],
        "empty_pages": [],
    }
    diff = {
        "candidates": candidates, "total_candidate_count": 9,
        "candidates_truncated": False,
    }
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "ollama_candidate_review_limit", 5)
    monkeypatch.setattr(settings, "ollama_candidate_batch_size", 2)
    seen = []

    def fake_openai_compact(content):
        payload = json.loads(content.split("\n\n", 1)[-1])
        ids = [item["candidate_id"] for item in payload["candidates"]]
        seen.extend(ids)
        return []

    monkeypatch.setattr(
        "app.services.ai_service._analyse_with_openai_compact",
        fake_openai_compact,
    )
    draft = analyse_documents(earlier, later, diff)
    assert seen == ["C01", "C02", "C03", "C04", "C05"]
    assert draft.candidate_review_metadata["strategy"] == "ranked_batched_candidate_review"
    assert draft.candidate_review_metadata["reviewed_candidates"] == 5
    assert draft.candidate_review_metadata["batches_succeeded"] == 3
    assert any("5 selected candidates out of 9" in item for item in draft.limitations)
