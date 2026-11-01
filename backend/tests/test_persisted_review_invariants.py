from app.services.analysis_service import _enforce_persisted_review_invariants


def test_persisted_payload_forces_all_removals_to_review():
    payload = {
        "changes": [
            {"change_type": "removed", "review_required": False},
            {"change_type": "added", "review_required": False},
            {"change_type": "removed", "review_required": False},
        ],
        "counts": {"total": 3, "needs_review": 0},
        "overall_review_required": False,
    }
    result = _enforce_persisted_review_invariants(payload)
    assert result["changes"][0]["review_required"] is True
    assert result["changes"][1]["review_required"] is False
    assert result["changes"][2]["review_required"] is True
    assert result["counts"]["needs_review"] == 2
    assert result["overall_review_required"] is True
    assert result["changes"][0]["removal_verification"]["confirmed_repeal"] is False


def test_persisted_payload_guard_handles_json_text():
    import json
    payload = {
        "result": {
            "changes": [{"change_type": "removed", "review_required": False}],
            "counts": {"needs_review": 0},
            "overall_review_required": False,
        }
    }
    result = _enforce_persisted_review_invariants(json.dumps(payload))
    decoded = json.loads(result)
    inner = decoded["result"]
    assert inner["changes"][0]["review_required"] is True
    assert inner["counts"]["needs_review"] == 1
    assert inner["overall_review_required"] is True



def test_persisted_payload_forces_unpaired_candidate_to_human_review():
    payload = {
        "changes": [
            {
                "change_type": "added",
                "review_required": False,
                "pairing_verification": {
                    "status": "unrelated_old_new_pair_rejected",
                    "pairing_verified": False,
                },
                "evidence_verified": True,
            }
        ],
        "counts": {"total": 1, "needs_review": 0},
        "overall_review_required": False,
    }
    result = _enforce_persisted_review_invariants(payload)
    change = result["changes"][0]
    assert change["review_required"] is True
    assert "same provision" in change["evidence_warning"]
    assert result["counts"]["needs_review"] == 1
    assert result["overall_review_required"] is True


def test_persisted_payload_flags_partial_candidate_review_coverage():
    payload = {
        "changes": [],
        "counts": {"total": 0, "needs_review": 0},
        "overall_review_required": False,
        "candidate_review_metadata": {
            "detected_candidates": 451,
            "selected_candidates": 64,
            "reviewed_candidates": 64,
        },
        "limitations": [],
    }
    result = _enforce_persisted_review_invariants(payload)
    assert result["overall_review_required"] is True
    assert any("64 of 451" in item for item in result["limitations"])
