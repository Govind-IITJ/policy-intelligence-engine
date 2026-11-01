"""Orchestrate comparison, evidence checks and persistence."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from typing import Any

from app import database
from app.services.ai_service import analyse_documents
from app.services.diff_service import build_deterministic_diff, normalize_text


def _tokens(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u00ad", "").replace("\u200b", "")
    value = re.sub(
        r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)",
        "",
        value,
    )
    return re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE)


def _contains_exact_token_sequence(page_text: str, phrase: str) -> bool:
    page_tokens = _tokens(page_text)
    phrase_tokens = _tokens(phrase)

    if not page_tokens or not phrase_tokens:
        return False

    width = len(phrase_tokens)
    return any(
        page_tokens[index:index + width] == phrase_tokens
        for index in range(len(page_tokens) - width + 1)
    )


def _quote_exists(
    pages: list[dict[str, Any]],
    page_number: int | None,
    quote: str,
) -> bool:
    if not isinstance(page_number, int) or isinstance(page_number, bool):
        return False

    if not quote or not quote.strip():
        return False

    page = next(
        (item for item in pages if item.get("page") == page_number),
        None,
    )

    if page is None:
        return False

    # Exact contiguous word sequence; punctuation and PDF whitespace changes
    # are ignored, but missing, inserted or reordered words are not.
    return _contains_exact_token_sequence(
        str(page.get("text") or ""),
        quote,
    )


def _excerpt_exists(
    pages: list[dict[str, Any]],
    page_number: int | None,
    excerpt: str,
) -> bool:
    return _quote_exists(pages, page_number, excerpt)


def _required_evidence(change: dict[str, Any]) -> tuple[bool, bool]:
    change_type = str(change.get("change_type", ""))

    if change_type == "added":
        return False, True
    if change_type == "removed":
        return True, False

    return True, True


_PAIR_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "was", "were", "are", "is", "be", "been", "being", "to", "of", "in",
    "on", "at", "by", "as", "an", "a", "or", "it", "its", "all", "each",
    "any", "such", "will", "would", "should", "may", "can", "could", "shall",
    "must", "not", "under", "before", "after", "during", "within", "into",
    "their", "them", "they", "he", "she", "his", "her", "who", "which",
    "what", "when", "where", "how", "than", "then", "also", "only", "other",
    "new", "old", "version", "document", "policy", "scheme", "guideline",
    "guidelines", "clause", "section", "unit", "units", "setup", "set",
    "applicant", "applicants", "beneficiary", "beneficiaries", "pm", "kisan",
    "pmkisan", "under", "thereof", "therein", "herein", "provided",
}

# These anchors distinguish policy subjects that can otherwise share generic
# words such as "eligibility", "benefit", "applicant" or "requirement".
_PAIR_TOPIC_PATTERNS = (
    ("inheritance_transfer", re.compile(
        r"\b(?:inherit\w*|transferees?|succession|successors?|heirs?|mutation)\b", re.I
    )),
    ("eligibility_cutoff", re.compile(
        r"\b(?:cut[\s-]?off|thereafter)\b", re.I
    )),
    ("land_entry_window", re.compile(
        r"\b(?:date of entry|land entry|entry of land)\b", re.I
    )),
    ("physical_verification", re.compile(r"\bphysical\s+verification\b", re.I)),
    ("edp_training", re.compile(r"\bedp\s+training\b", re.I)),
    ("udyam_registration", re.compile(r"\budyam\b", re.I)),
    ("aadhaar_kyc", re.compile(r"\b(?:aadhaar|aadhar|e-?kyc)\b", re.I)),
    ("margin_money", re.compile(r"\bmargin\s+money\b", re.I)),
    ("bank_account", re.compile(r"\b(?:bank|beneficiary|loan)\s+account\b", re.I)),
    ("project_cost", re.compile(r"\bproject\s+cost\b", re.I)),
    ("age_limit", re.compile(r"\b(?:age|years?\s+of\s+age)\b", re.I)),
    ("landholding", re.compile(r"\b(?:landholding|land\s+holding|hectares?)\b", re.I)),
)


def _pair_content_tokens(value: str) -> set[str]:
    tokens = _tokens(value or "")
    result = set()
    for token in tokens:
        if token in _PAIR_STOPWORDS or len(token) < 3:
            continue
        # Light stemming helps "beneficiary/beneficiaries" and similar forms
        # without bringing in a heavyweight NLP dependency.
        if token.endswith("ies") and len(token) > 5:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 4:
            token = token[:-1]
        result.add(token)
    return result


def _pair_topic_anchors(value: str) -> set[str]:
    text = str(value or "")
    return {
        name for name, pattern in _PAIR_TOPIC_PATTERNS
        if pattern.search(text)
    }


def _provision_pair_score(left_text: str, right_text: str) -> dict[str, Any]:
    """Measure topical correspondence; this is not legal-equivalence proof."""
    left = str(left_text or "").strip()
    right = str(right_text or "").strip()
    left_terms = _pair_content_tokens(left)
    right_terms = _pair_content_tokens(right)
    overlap = left_terms & right_terms
    union = left_terms | right_terms
    jaccard = len(overlap) / max(1, len(union))
    containment = len(overlap) / max(1, min(len(left_terms), len(right_terms)))
    sequence = SequenceMatcher(
        None,
        normalize_text(left),
        normalize_text(right),
        autojunk=False,
    ).ratio()
    left_anchors = _pair_topic_anchors(left)
    right_anchors = _pair_topic_anchors(right)
    shared_anchors = left_anchors & right_anchors
    conflicting_anchors = bool(
        left_anchors and right_anchors and not shared_anchors
    )

    score = (0.45 * jaccard) + (0.30 * containment) + (0.25 * sequence)
    if shared_anchors:
        score += 0.20
    if conflicting_anchors:
        score = 0.0

    # A shared specific topic is a strong correspondence clue, but still needs
    # some contextual overlap to avoid matching on one generic word.
    if conflicting_anchors:
        compatible = False
    elif shared_anchors:
        compatible = len(overlap) >= 2 or any(
            anchor in ("udyam_registration", "aadhaar_kyc")
            for anchor in shared_anchors
        )
    else:
        compatible = (
            len(overlap) >= 3
            and containment >= 0.28
            and jaccard >= 0.10
            and score >= 0.19
        )

    return {
        "compatible": compatible,
        "score": round(score, 4),
        "overlap_terms": sorted(overlap),
        "left_topic_anchors": sorted(left_anchors),
        "right_topic_anchors": sorted(right_anchors),
        "shared_topic_anchors": sorted(shared_anchors),
        "conflicting_topic_anchors": conflicting_anchors,
        "method": "weighted lexical overlap plus policy-topic anchors",
        "is_legal_equivalence_test": False,
    }


def _passage_windows(page_text: str, max_segments: int = 3) -> list[str]:
    text = str(page_text or "").strip()
    if not text:
        return []
    # PDF extraction often breaks clauses at line boundaries. Include short
    # adjacent windows so headings/conditions that span lines remain searchable.
    segments = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"(?<=[.!?;:])\s+|\r?\n+", text)
        if len(part.strip()) >= 8
    ]
    windows: list[str] = []
    for start in range(len(segments)):
        for width in range(1, min(max_segments, len(segments) - start) + 1):
            candidate = " ".join(segments[start:start + width]).strip()
            if candidate and len(candidate) <= 1800:
                windows.append(candidate)
    if not windows and len(text) <= 1800:
        windows.append(re.sub(r"\s+", " ", text))
    # Stable deduplication prevents repeated PDF line-wrap windows.
    return list(dict.fromkeys(windows))


def _find_related_provision(
    source_text: str,
    target_pages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Search every extracted page for a plausible same-subject counterpart.

    This is a recall guard. A match is only a candidate clause pair and always
    remains reviewable; a non-match never proves that a provision was repealed
    or newly introduced.
    """
    source = str(source_text or "").strip()
    if not source:
        return None

    best: dict[str, Any] | None = None
    for page in target_pages or []:
        page_number = page.get("page")
        for snippet in _passage_windows(str(page.get("text") or "")):
            scored = _provision_pair_score(source, snippet)
            if not scored["compatible"]:
                continue
            # Penalize tiny excerpts: they can match a generic phrase by chance.
            if len(_pair_content_tokens(snippet)) < 3:
                continue
            rank = scored["score"] + min(len(snippet), 500) / 10000
            if best is None or rank > best["rank"]:
                quote = snippet
                if len(quote) > 900:
                    quote = quote[:897].rsplit(" ", 1)[0] + "..."
                best = {
                    "page": page_number,
                    "quote": quote,
                    "score": scored["score"],
                    "rank": rank,
                    "overlap_terms": scored["overlap_terms"],
                    "topic_anchors": scored["shared_topic_anchors"],
                    "method": scored["method"],
                }
    return best


def _append_review_note(change: dict[str, Any], note: str) -> None:
    existing = str(change.get("explanation") or "").strip()
    if note.casefold() not in existing.casefold():
        change["explanation"] = (existing + " " if existing else "") + note
    change["review_required"] = True
    change["confidence"] = "low"


def _clear_old_side(change: dict[str, Any]) -> None:
    change["old_page"] = None
    change["old_text"] = ""
    change["old_quote"] = ""
    change["old_evidence_verified"] = None
    change["old_text_verified"] = None


def _clear_new_side(change: dict[str, Any]) -> None:
    change["new_page"] = None
    change["new_text"] = ""
    change["new_quote"] = ""
    change["new_evidence_verified"] = None
    change["new_text_verified"] = None


def _reconcile_change_pairing(
    change: dict[str, Any],
    earlier_pages: list[dict[str, Any]],
    later_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reject unrelated old/new excerpts and search the full opposite document."""
    change_type = str(change.get("change_type") or "").casefold()
    old_text = str(change.get("old_text") or change.get("old_quote") or "").strip()
    new_text = str(change.get("new_text") or change.get("new_quote") or "").strip()

    if change_type == "added":
        counterpart = _find_related_provision(new_text, earlier_pages)
        if counterpart:
            change["change_type"] = "modified"
            change["old_page"] = counterpart["page"]
            change["old_text"] = counterpart["quote"]
            change["old_quote"] = counterpart["quote"]
            change["pairing_verification"] = {
                "status": "earlier_counterpart_found",
                "pairing_verified": True,
                "counterpart_page": counterpart["page"],
                "match_score": counterpart["score"],
                "overlap_terms": counterpart["overlap_terms"],
                "topic_anchors": counterpart["topic_anchors"],
                "method": counterpart["method"],
                "human_review_required": True,
            }
            _append_review_note(
                change,
                "A potentially corresponding provision was located in the complete earlier document. "
                "This candidate may be a modification or relocated clause, not a confirmed addition; "
                "compare the full provisions and conditions.",
            )
            change["practical_action"] = (
                "Compare the complete earlier and later provisions before changing eligibility or procedure."
            )
            _neutralize_repaired_pair_explanation(change)
        else:
            _clear_old_side(change)
            change["addition_verification"] = {
                "status": "no_corresponding_earlier_passage_located",
                "search_scope": "all_extracted_earlier_document_pages",
                "confirmed_addition": False,
                "human_review_required": True,
            }
            change["pairing_verification"] = {
                "status": "one_sided_candidate",
                "pairing_verified": False,
                "human_review_required": True,
            }
            _append_review_note(
                change,
                "No same-subject earlier passage was located by the full-document search. "
                "This is a provisional addition candidate, not proof that the policy rule was newly introduced.",
            )
            change["practical_action"] = (
                "Review the corresponding section in the earlier policy before acting on this potential addition."
            )
        return change

    if change_type == "removed":
        counterpart = _find_related_provision(old_text, later_pages)
        change["review_required"] = True
        if counterpart:
            change["change_type"] = "modified"
            change["new_page"] = counterpart["page"]
            change["new_text"] = counterpart["quote"]
            change["new_quote"] = counterpart["quote"]
            change["removal_verification"] = {
                "status": "related_later_provision_found",
                "search_scope": "all_extracted_later_document_pages",
                "related_page": counterpart["page"],
                "related_quote": counterpart["quote"],
                "match_score": counterpart["score"],
                "overlap_terms": counterpart["overlap_terms"],
                "topic_anchors": counterpart["topic_anchors"],
                "confirmed_repeal": False,
            }
            change["pairing_verification"] = {
                "status": "later_counterpart_found",
                "pairing_verified": True,
                "match_score": counterpart["score"],
                "human_review_required": True,
            }
            _append_review_note(
                change,
                "Related subject matter was located in the complete later document. "
                "This is a provisional modification, not a confirmed repeal; review the full clauses, "
                "exceptions, annexes and cross-references.",
            )
            change["practical_action"] = (
                "Compare the complete earlier and later provisions and their exceptions before treating the rule as repealed."
            )
            _neutralize_repaired_pair_explanation(change)
        else:
            change["removal_verification"] = {
                "status": "no_corresponding_later_passage_located",
                "search_scope": "all_extracted_later_document_pages",
                "confirmed_repeal": False,
                "human_review_required": True,
            }
            change["pairing_verification"] = {
                "status": "one_sided_candidate",
                "pairing_verified": False,
                "human_review_required": True,
            }
            change["evidence_warning"] = (
                "No same-subject later passage was located by automated full-document search. "
                "Absence of a match does not establish repeal; inspect the complete later policy, "
                "annexes and renumbered provisions."
            )
            _append_review_note(
                change,
                "No same-subject later passage was located by automated full-document search. "
                "Absence of a match does not establish repeal; a human must inspect the complete later policy.",
            )
        return change

    if old_text and new_text:
        score = _provision_pair_score(old_text, new_text)
        if score["compatible"]:
            change["pairing_verification"] = {
                "status": "subject_pair_compatible",
                "pairing_verified": True,
                **score,
                "human_review_required": False,
            }
            return change

        # The deterministic sequence aligner may have paired adjacent but
        # unrelated text. Search the complete earlier document for the actual
        # counterpart of the later passage before keeping that source citation.
        rejected_old_page = change.get("old_page")
        counterpart = _find_related_provision(new_text, earlier_pages)
        if counterpart:
            change["old_page"] = counterpart["page"]
            change["old_text"] = counterpart["quote"]
            change["old_quote"] = counterpart["quote"]
            change["pairing_verification"] = {
                "status": "earlier_counterpart_repaired",
                "pairing_verified": True,
                "rejected_old_page": rejected_old_page,
                "counterpart_page": counterpart["page"],
                "match_score": counterpart["score"],
                "overlap_terms": counterpart["overlap_terms"],
                "topic_anchors": counterpart["topic_anchors"],
                "method": counterpart["method"],
                "human_review_required": True,
            }
            _neutralize_repaired_pair_explanation(change)
            anchors = set((change.get("pairing_verification") or {}).get("topic_anchors") or [])
            if "inheritance_transfer" in anchors:
                change["title"] = "Inheritance-related land transfer provision"
            elif "eligibility_cutoff" in anchors:
                change["title"] = "Eligibility cut-off provision"
            else:
                change["title"] = "Potentially corresponding provision across versions"
            _append_review_note(
                change,
                "The original earlier excerpt did not match the subject of the later excerpt and was replaced "
                "with a candidate counterpart found by searching the complete earlier document. "
                "Human review is required to confirm the clause relationship.",
            )
            return change

        # Do not let an exact quotation match on the wrong topic make a false
        # old/new pair appear evidence-verified.
        rejected_page = change.get("old_page")
        _clear_old_side(change)
        original_type = change.get("change_type")
        change["change_type"] = "added"
        change["addition_verification"] = {
            "status": "earlier_counterpart_not_located_after_rejecting_unrelated_pair",
            "search_scope": "all_extracted_earlier_document_pages",
            "confirmed_addition": False,
            "rejected_earlier_page": rejected_page,
            "original_change_type": original_type,
            "pairing_diagnostics": score,
            "human_review_required": True,
        }
        change["pairing_verification"] = {
            "status": "unrelated_old_new_pair_rejected",
            "pairing_verified": False,
            "rejected_earlier_page": rejected_page,
            "diagnostics": score,
            "human_review_required": True,
        }
        _append_review_note(
            change,
            "The supplied earlier quotation was found on its cited page but concerns a different subject "
            "from the later quotation. It has been detached from this finding. No corresponding earlier "
            "provision was located; treat this as a provisional addition candidate, not a confirmed new rule.",
        )
        change["practical_action"] = (
            "Review the complete corresponding sections in both policy versions before taking action."
        )
        return change

    # Non-add/remove changes without a two-sided source must not be treated as
    # paired modifications. Search the missing side across the complete document.
    if new_text and not old_text:
        return _reconcile_change_pairing(
            {**change, "change_type": "added"}, earlier_pages, later_pages
        )
    if old_text and not new_text:
        return _reconcile_change_pairing(
            {**change, "change_type": "removed"}, earlier_pages, later_pages
        )

    change["pairing_verification"] = {
        "status": "missing_source_text",
        "pairing_verified": False,
        "human_review_required": True,
    }
    change["review_required"] = True
    change["confidence"] = "low"
    return change


def _neutralize_repaired_pair_explanation(change: dict[str, Any]) -> None:
    """Replace stale AI rationale after the backend changes either source side.

    AI explanations refer to the original candidate snippets. Once deterministic
    reconciliation replaces a quote/page, retaining that explanation can create
    a false narrative even though the new quotations match their pages.
    """
    old_text = re.sub(r"\s+", " ", str(change.get("old_quote") or change.get("old_text") or "")).strip()
    new_text = re.sub(r"\s+", " ", str(change.get("new_quote") or change.get("new_text") or "")).strip()
    if old_text and new_text:
        old_short = old_text[:220].rstrip()
        new_short = new_text[:220].rstrip()
        change["explanation"] = (
            "Automated reconciliation located potentially corresponding passages in both versions. "
            f"Earlier text: ‘{old_short}’. Later text: ‘{new_short}’. "
            "The substantive policy effect is not established by passage matching; human review is required."
        )
    else:
        change["explanation"] = (
            "The original source pairing was rejected or replaced. The available evidence does not "
            "establish the precise policy effect; review the complete provision in both versions."
        )
    change["confidence"] = "low"
    change["review_required"] = True
    change["interpretation_verified"] = False
    change["interpretation_status"] = "automated_pairing_only_human_interpretation_required"
    change["practical_action"] = (
        "Review the complete corresponding clauses, definitions, exceptions and cross-references "
        "before changing any eligibility or operational decision."
    )


def _same_payment_frequency(left: str, right: str) -> bool:
    def frequency(text: str) -> str | None:
        value = normalize_text(text).replace("four", "4").replace("three", "3")
        if "installment" not in value and "installment" not in value:
            return None
        if re.search(r"(?:every|each)\s+4\s*(?:-|\s)?months?", value):
            return "4_months"
        if re.search(r"(?:every|each)\s+3\s*(?:-|\s)?months?", value):
            return "3_months"
        return None
    left_frequency = frequency(left)
    return bool(left_frequency and left_frequency == frequency(right))


def _same_policy_fact_restatement(change: dict[str, Any]) -> str | None:
    """Conservative filter for source pairs that restate the same fact.

    This is intentionally narrow. It suppresses a finding from the change list
    only when both cited excerpts independently express the same key fact.
    It does not infer legal equivalence from a general semantic similarity.
    """
    left = str(change.get("old_quote") or change.get("old_text") or "").strip()
    right = str(change.get("new_quote") or change.get("new_text") or "").strip()
    if not left or not right:
        return None
    left_n = normalize_text(left)
    right_n = normalize_text(right)
    left_tokens = _pair_content_tokens(left)
    right_tokens = _pair_content_tokens(right)
    if len(left_tokens) < 3 or len(right_tokens) < 3:
        return None

    seq = SequenceMatcher(None, left_n, right_n, autojunk=False).ratio()
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / max(1, len(union))
    # A wording match must never suppress a finding when its cited numeric
    # facts differ (e.g. an income threshold changing from 200,000 to 300,000).
    numeric_left = _numeric_facts(left)
    numeric_right = _numeric_facts(right)
    numeric_conflict = bool(numeric_left or numeric_right) and numeric_left != numeric_right
    if not numeric_conflict and seq >= 0.90 and jaccard >= 0.72:
        return "near_identical_source_passages_no_material_wording_change"

    # Same explicit four-month installment interval in both cited excerpts.
    if _same_payment_frequency(left, right):
        return "same_four_month_installment_frequency_in_both_versions"

    # Same cut-off date and unchanged eligibility freeze language.
    dates_left = set(re.findall(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b", left))
    dates_right = set(re.findall(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b", right))
    date_key = lambda values: {re.sub(r"[./-]", "", v) for v in values}
    if (
        date_key(dates_left) & date_key(dates_right)
        and "eligibility" in left_n and "eligibility" in right_n
        and ("thereafter" in left_n or "no changes" in left_n)
        and ("thereafter" in right_n or "no changes" in right_n)
    ):
        return "same_eligibility_cutoff_and_freeze_date_in_both_versions"

    # Both excerpts state direct payment into bank accounts / DBT.
    if (
        "bank" in left_tokens and "bank" in right_tokens
        and ({"direct", "directly", "dbt"} & left_tokens)
        and ({"direct", "directly", "dbt"} & right_tokens)
        and ("account" in left_tokens or "accounts" in left_tokens)
        and ("account" in right_tokens or "accounts" in right_tokens)
    ):
        return "same_direct_bank_account_payment_mechanism_in_both_versions"

    # Same stated annual amount is a restatement, not a detected amendment by itself.
    def annual_amount(text: str) -> tuple[str, str] | None:
        norm = normalize_text(text).replace(",", "")
        amounts = re.findall(r"(?:rs\.?|inr|₹)\s*(\d+(?:\.\d+)?)", norm)
        annual = bool(re.search(r"\b(?:per\s+year|per\s+annum|annually|yearly)\b", norm))
        if amounts and annual:
            return (amounts[0], "annual")
        return None
    amount_left, amount_right = annual_amount(left), annual_amount(right)
    if amount_left and amount_left == amount_right:
        return "same_annual_benefit_amount_restated_in_both_versions"

    return None


def _finding_tokens(change: dict[str, Any]) -> set[str]:
    joined = " ".join(str(change.get(key) or "") for key in (
        "title", "old_text", "new_text", "old_quote", "new_quote"
    ))
    return _pair_content_tokens(joined)


def _suppress_non_material_and_duplicate_findings(
    changes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep only distinct candidate changes; return transparent suppression ledger."""
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    seen_all: list[dict[str, Any]] = []
    for change in changes:
        old_text = str(change.get("old_quote") or change.get("old_text") or "").strip()
        new_text = str(change.get("new_quote") or change.get("new_text") or "").strip()
        tokens = _finding_tokens(change)

        # Detect duplicates against every earlier candidate, including one
        # suppressed as a no-op. Otherwise a duplicate of a suppressed no-op
        # could accidentally survive as a new finding.
        duplicate_of = None
        for existing in seen_all:
            other_tokens = _finding_tokens(existing)
            overlap = len(tokens & other_tokens) / max(1, len(tokens | other_tokens))
            shared = tokens & other_tokens
            payment_duplicate = (
                {"duplication", "payment"}.issubset(shared)
                and len(shared & {"duplication", "payment", "eligible", "family", "transferred", "ensure"}) >= 4
            )
            title_similarity = SequenceMatcher(
                None,
                normalize_text(str(change.get("title") or "")),
                normalize_text(str(existing.get("title") or "")),
                autojunk=False,
            ).ratio()
            if overlap >= 0.68 or title_similarity >= 0.84 or payment_duplicate:
                duplicate_of = existing
                break
        seen_all.append(change)

        if duplicate_of:
            suppressed.append({
                "title": change.get("title", "Untitled candidate"),
                "change_id": change.get("change_id"),
                "source_explanation": change.get("explanation", ""),
                "reason": "duplicate_or_overlapping_finding",
                "duplicate_of": duplicate_of.get("change_id") or duplicate_of.get("title"),
                "disposition": "merged_into_existing_finding",
                "review_required": True,
            })
            if duplicate_of in kept:
                duplicate_of["duplicate_candidates_merged"] = int(
                    duplicate_of.get("duplicate_candidates_merged", 0)
                ) + 1
                duplicate_of["review_required"] = True
            continue

        # Tiny, contextless fragments cannot support a useful finding.
        if (not old_text and len(_pair_content_tokens(new_text)) < 3) or (
            not new_text and len(_pair_content_tokens(old_text)) < 3
        ):
            suppressed.append({
                "title": change.get("title", "Untitled candidate"),
                "change_id": change.get("change_id"),
                "source_explanation": change.get("explanation", ""),
                "reason": "incomplete_fragment_insufficient_context",
                "disposition": "suppressed_from_report",
                "review_required": True,
            })
            continue

        restatement = _same_policy_fact_restatement(change)
        if restatement:
            suppressed.append({
                "title": change.get("title", "Untitled candidate"),
                "change_id": change.get("change_id"),
                "source_explanation": change.get("explanation", ""),
                "reason": restatement,
                "disposition": "not_reported_as_substantive_change",
                "old_page": change.get("old_page"),
                "new_page": change.get("new_page"),
                "review_required": True,
            })
            continue

        kept.append(change)
    return kept, suppressed


_NUMBER_RE = re.compile(
    r"(?<![\w])"
    r"(?:(?:₹|INR\s*|Rs\.?\s*)?)"
    r"(\d[\d,]*(?:\.\d+)?)"
    r"\s*(%|percent|lakhs?|crores?)?",
    flags=re.IGNORECASE,
)


def _numeric_facts(value: str) -> set[str]:
    facts: set[str] = set()

    for match in _NUMBER_RE.finditer(value or ""):
        raw_number = match.group(1).replace(",", "")
        unit = (match.group(2) or "").casefold()

        try:
            number = Decimal(raw_number)
        except InvalidOperation:
            continue

        if unit.startswith("lakh"):
            number *= Decimal(100000)
            suffix = ""
        elif unit.startswith("crore"):
            number *= Decimal(10000000)
            suffix = ""
        elif unit in ("%", "percent"):
            suffix = "%"
        else:
            suffix = ""

        canonical = format(number.normalize(), "f")
        facts.add(canonical + suffix)

    return facts


_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


_FREQUENCY_TERMS = {
    "quarterly": 4,
    "quarter": 4,
    "annually": 1,
    "annual": 1,
    "yearly": 1,
    "monthly": 12,
    "semiannually": 2,
    "biannual": 2,
    "weekly": 52,
    "fortnightly": 26,
    "daily": 365,
}


def _frequency_claims(value: str) -> set[int]:
    value = (value or "").casefold()
    frequencies: set[int] = set()

    for term, count in _FREQUENCY_TERMS.items():
        if re.search(r"\b" + re.escape(term) + r"\b", value):
            frequencies.add(count)

    number_pattern = "|".join(
        [str(number) for number in range(1, 13)]
        + list(_WORD_NUMBERS.keys())
    )

    pattern = (
        r"\b(" + number_pattern + r")\s+times?\s+"
        r"(?:per|a|each)\s+(?:year|annum)\b"
    )

    for match in re.finditer(pattern, value):
        raw = match.group(1)
        count = int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]
        frequencies.add(count)

    if re.search(r"\bonce\s+(?:per|a)\s+year\b", value):
        frequencies.add(1)

    if re.search(r"\btwice\s+(?:per|a)\s+year\b", value):
        frequencies.add(2)

    return frequencies


def _numeric_claim_warnings(
    source_text: str,
    claim_text: str,
) -> list[str]:
    unsupported = sorted(
        _numeric_facts(claim_text) - _numeric_facts(source_text)
    )

    if not unsupported:
        return []

    return [
        "Numerical claims not found in the cited source text: "
        + ", ".join(unsupported[:10])
    ]


def _frequency_consistency_warnings(
    source_text: str,
    explanation: str,
) -> list[str]:
    source_frequencies = _frequency_claims(source_text)
    claimed_frequencies = _frequency_claims(explanation)

    unsupported = sorted(claimed_frequencies - source_frequencies)

    if not unsupported:
        return []

    return [
        "The explanation states a reporting frequency not supported by "
        "the source wording: "
        + ", ".join(str(value) for value in unsupported)
        + " times per year."
    ]


def _change_consistency_warnings(
    change: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []

    old_quote = str(change.get("old_quote") or "")
    new_quote = str(change.get("new_quote") or "")
    old_text = str(change.get("old_text") or "")
    new_text = str(change.get("new_text") or "")
    explanation = str(change.get("explanation") or "")

    warnings.extend(_numeric_claim_warnings(old_quote, old_text))
    warnings.extend(_numeric_claim_warnings(new_quote, new_text))

    source_text = " ".join((old_quote, new_quote, old_text, new_text))
    warnings.extend(_numeric_claim_warnings(source_text, explanation))
    warnings.extend(
        _frequency_consistency_warnings(source_text, explanation)
    )

    return list(dict.fromkeys(warnings))


def _neutralize_unsupported_explanation(
    change: dict[str, Any], warnings: list[str]
) -> None:
    """Replace unsupported numeric/frequency interpretations with cautious source-grounded text."""
    if not warnings:
        return

    old_quote = str(change.get("old_quote") or "").strip()
    new_quote = str(change.get("new_quote") or "").strip()
    title_and_sources = " ".join((
        str(change.get("title") or ""), old_quote, new_quote,
        str(change.get("old_text") or ""), str(change.get("new_text") or ""),
    )).casefold()
    is_frequency_warning = any("frequency" in warning.casefold() for warning in warnings)

    if is_frequency_warning and any(
        token in title_and_sources for token in ("union territory", "ut government", "trimester", "4-month")
    ):
        change["title"] = "UT payment-period provision (interpretation unverified)"
    elif not old_quote and new_quote and any(
        token in title_and_sources for token in ("eligibility", "family", "cut-off", "cutoff")
    ):
        change["title"] = "Family eligibility provision (date interpretation unverified)"
    else:
        change["title"] = "Potential policy provision (interpretation unverified)"

    if old_quote and new_quote:
        safe_explanation = (
            "The cited earlier and later excerpts are located on their stated pages. "
            "The automated consistency check found numeric or frequency claims in the original explanation "
            "that are not supported by the cited excerpts. The substantive policy effect is therefore "
            "not established by this result. Review the complete clauses, conditions and cross-references "
            "before classifying the provision as changed."
        )
    elif new_quote:
        safe_explanation = (
            "The cited passage is present in the later version. The automated consistency check found "
            "numeric or frequency claims in the original explanation that are not supported by the cited "
            "excerpt. A corresponding earlier provision has not been established, so this is a provisional "
            "candidate rather than a confirmed addition. Review the complete earlier policy before acting."
        )
    elif old_quote:
        safe_explanation = (
            "The cited passage is present in the earlier version. The automated consistency check found "
            "numeric or frequency claims in the original explanation that are not supported by the cited "
            "excerpt. A corresponding later provision has not been established; absence of a match does "
            "not prove repeal. Review the complete later policy before classifying this as removed."
        )
    else:
        safe_explanation = (
            "The original explanation contains numeric or frequency claims that could not be verified "
            "against the available source quotations. No substantive policy effect is asserted. "
            "Review the complete source provisions manually."
        )

    change["explanation"] = safe_explanation
    change["explanation_validation"] = {
        "status": "unsupported_claims_neutralized",
        "method": "numeric_and_frequency_claims_checked_against_cited_excerpts",
        "warnings": list(warnings),
        "human_review_required": True,
    }
    change["review_required"] = True
    change["confidence"] = "low"


def _possible_excerpt_context_warnings(change: dict[str, Any]) -> list[str]:
    """Flag short quotations that look like cut-off fragments; do not infer clause completeness."""
    warnings: list[str] = []
    for side in ("old", "new"):
        quote = str(change.get(f"{side}_quote") or "").strip().strip('“”\"')
        if not quote:
            continue
        word_count = len(_tokens(quote))
        if word_count < 35 and quote[-1:] not in (".", "!", "?", ";", ":"):
            warnings.append(
                f"The {side} quotation is a short excerpt without a clear sentence ending; surrounding clause context may be missing."
            )
    return warnings


def _page_has_text(document: dict[str, Any], page_number: Any) -> bool:
    return bool(
        isinstance(page_number, int)
        and not isinstance(page_number, bool)
        and 1 <= page_number <= int(document.get("page_count") or 0)
        and str(document["pages"][page_number - 1].get("text") or "").strip()
    )


def _build_final_action_checklist(
    changes: list[dict[str, Any]],
    earlier: dict[str, Any],
    later: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build actions only from retained findings, with stable finding traceability."""
    actions: list[dict[str, Any]] = []
    for index, change in enumerate(changes, start=1):
        change_type = str(change.get("change_type") or "other").casefold()
        pairing_verified = change.get("pairing_verified") is True

        if change_type == "removed":
            source_role, source_page, source_quote_verified = (
                "earlier", change.get("old_page"), change.get("old_evidence_verified") is True
            )
            source_document = earlier
        else:
            source_role, source_page, source_quote_verified = (
                "later", change.get("new_page"), change.get("new_evidence_verified") is True
            )
            source_document = later

        source_verified = bool(source_quote_verified and _page_has_text(source_document, source_page))
        practical_action = str(change.get("practical_action") or "").strip()
        safe_verbs = ("review", "verify", "compare", "inspect", "check", "confirm", "examine")
        action_is_review_oriented = any(verb in practical_action.casefold() for verb in safe_verbs)

        if not source_verified:
            action_text = "Verify the quoted source passage and its page before interpreting this finding."
            source_warning = "The action's cited source quote/page has not been verified."
        elif not pairing_verified or change_type in ("added", "removed"):
            action_text = (
                "Review the complete earlier and later provisions, including definitions, exceptions, "
                "annexes and cross-references, before treating this as an addition or removal."
            )
            source_warning = (
                "The quotation location is verified, but earlier/later clause correspondence or "
                "addition/removal status is not established."
            )
        elif not action_is_review_oriented:
            action_text = "Have a policy reviewer compare the complete clauses and confirm the substantive effect before operational use."
            source_warning = "Automated clause pairing does not verify the legal or operational interpretation."
        else:
            action_text = practical_action
            source_warning = "Automated clause pairing is not independent human verification of the policy interpretation."

        change_id = str(change.get("change_id") or f"CHG-{index:03d}")
        title = str(change.get("title") or "Retained finding")
        actions.append({
            "action_id": f"ACT-{index:03d}",
            "change_id": change_id,
            "action": action_text,
            "reason": f"Retained finding: {title}. This item is a review task, not an instruction to change policy operations.",
            "source_document": source_role if source_page is not None else "none",
            "source_page": source_page,
            "source_verified": source_verified,
            "review_required": True,
            "source_warning": source_warning,
        })
    return actions


_REMOVAL_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "was", "were", "are", "is", "be", "been", "being", "to", "of", "in",
    "on", "at", "by", "as", "an", "a", "or", "it", "its", "all", "each",
    "any", "such", "will", "would", "should", "may", "can", "could", "shall",
    "must", "not", "under", "before", "after", "during", "within", "into",
    "their", "them", "they", "he", "she", "his", "her", "who", "which",
    "what", "when", "where", "how", "than", "then", "also", "only", "other",
    "other", "new", "old", "version", "document", "policy", "guideline",
    "guidelines", "clause", "section", "unit", "units", "setup", "set", "up",
    "undergo", "undergone", "beneficiary", "beneficiaries", "applicant", "applicants",
}


def _removal_tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) >= 3 and token not in _REMOVAL_STOPWORDS
    }


def _find_related_later_provision(change: dict[str, Any], later_pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a later-version passage on the same subject as a claimed removal.

    This is a conservative recall guard, not a legal-equivalence classifier. A
    match forces manual review and converts a one-sided removal into a two-sided
    provisional modification so both versions' evidence can be inspected.
    """
    old_quote = str(change.get("old_quote") or "")
    title = str(change.get("title") or "")
    source_tokens = _removal_tokens(old_quote)
    if len(source_tokens) < 2:
        source_tokens = _removal_tokens(title + " " + old_quote)
    if len(source_tokens) < 2:
        return None

    # Require a meaningful subject anchor for common multi-word policy subjects.
    subject_anchors = []
    source_text = (title + " " + old_quote).casefold()
    for phrase in (
        ("physical", "verification"),
        ("edp", "training"),
        ("udyam", "registration"),
        ("margin", "money"),
        ("project", "cost"),
        ("bank", "loan"),
        ("beneficiary", "contribution"),
    ):
        if all(term in source_text for term in phrase):
            subject_anchors.append(set(phrase))

    best: dict[str, Any] | None = None
    for page in later_pages:
        page_text = str(page.get("text") or "")
        if not page_text.strip():
            continue
        # Keep sentence boundaries where possible and evaluate adjacent pairs to
        # tolerate PDF line wraps and split sentences.
        segments = [part.strip() for part in re.split(r"(?<=[;:!?])\s+|(?<=\.)\s+(?=[A-Z])|\n+", page_text) if part.strip()]
        windows = list(segments)
        windows.extend(
            segments[index] + " " + segments[index + 1]
            for index in range(len(segments) - 1)
        )
        for snippet in windows:
            candidate_tokens = _removal_tokens(snippet)
            overlap = source_tokens & candidate_tokens
            if len(overlap) < 2:
                continue
            anchor_match = any(anchor.issubset(candidate_tokens) for anchor in subject_anchors)
            jaccard = len(overlap) / max(1, len(source_tokens | candidate_tokens))
            source_recall = len(overlap) / max(1, len(source_tokens))
            # A named subject anchor is strong evidence of possible continuation;
            # otherwise require broader token overlap to avoid generic-word hits.
            if not anchor_match and (len(overlap) < 3 or jaccard < 0.16):
                continue
            score = (0.65 if anchor_match else 0.0) + (0.25 * jaccard) + (0.10 * source_recall)
            if re.search(r"\b(no|not|optional|exempt)\b.{0,35}\b(mandatory|required|compulsory)\b", snippet, re.IGNORECASE):
                score -= 0.18
            elif re.search(r"\b(mandatory|required|compulsory)\b", snippet, re.IGNORECASE):
                score += 0.08
            quote = snippet.strip()
            if len(quote) > 520:
                quote = quote[:517].rsplit(" ", 1)[0] + "..."
            if best is None or score > best["score"]:
                best = {
                    "page": page.get("page"),
                    "quote": quote,
                    "score": round(score, 4),
                    "overlap_terms": sorted(overlap),
                    "anchor_match": anchor_match,
                }
    return best


def _guard_removed_change(change: dict[str, Any], later_pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Prevent absence of an aligned excerpt from being presented as proven repeal."""
    if str(change.get("change_type", "")).casefold() != "removed":
        return change

    related = _find_related_later_provision(change, later_pages)
    change["review_required"] = True
    if related and isinstance(related.get("page"), int) and related.get("quote"):
        original_explanation = str(change.get("explanation") or "").strip()
        change["change_type"] = "modified"
        change["new_page"] = related["page"]
        change["new_quote"] = related["quote"]
        change["explanation"] = (
            (original_explanation + " ") if original_explanation else ""
        ) + (
            "A related provision was found in the later version on page "
            f"{related['page']}. The earlier wording therefore cannot be treated as a "
            "confirmed repeal; this is provisionally classified as a possible modification "
            "and requires human review."
        )
        change["removal_verification"] = {
            "status": "related_later_provision_found",
            "related_page": related["page"],
            "related_quote": related["quote"],
            "match_score": related["score"],
            "overlap_terms": related["overlap_terms"],
            "anchor_match": related["anchor_match"],
            "interpretation": "possible_modification_not_proven_repeal",
        }
        change["evidence_warning"] = (
            "Related text exists in the later version. Do not report this as a repeal without "
            "reviewing both provisions and their full surrounding sections."
        )
    else:
        change["removal_verification"] = {
            "status": "not_established",
            "interpretation": "absence_of_match_is_not_proof_of_repeal",
        }
        change["evidence_warning"] = (
            "No related later passage was detected by the automated recall guard. This does "
            "not prove repeal: verify the complete corresponding section, annexes and any "
            "renumbered provisions manually before treating this as removed."
        )
    return change



def _strict_later_subject_passage(change, later_pages):
    # Find a later-version passage on the same named policy subject.
    # This is a conservative recall guard, not a legal-equivalence test.
    source_text = (str(change.get("title") or "") + " " + str(change.get("old_quote") or "")).casefold()
    source_tokens = set(re.findall(r"[a-z0-9]+", source_text))

    anchors = [
        (("physical", "verification"), ("physical", "verification")),
        (("edp", "training"), ("edp", "training")),
        (("udyam",), ("udyam",)),
        (("margin", "money"), ("margin", "money")),
        (("project", "cost"), ("project", "cost")),
        (("eligibility",), ("eligibility",)),
        (("registration",), ("registration",)),
        (("subsidy",), ("subsidy",)),
    ]
    selected_anchor = None
    for source_anchor, required in anchors:
        if all(term in source_tokens for term in source_anchor):
            selected_anchor = required
            break

    stop = {
        "the", "and", "for", "with", "from", "that", "this", "these", "those",
        "was", "were", "are", "is", "be", "been", "being", "to", "of", "in",
        "on", "at", "by", "as", "an", "a", "or", "it", "its", "all", "each",
        "any", "such", "will", "would", "should", "may", "can", "could", "shall",
        "must", "not", "under", "before", "after", "during", "within", "into",
        "their", "them", "they", "who", "which", "what", "when", "where", "how",
        "than", "then", "also", "only", "other", "new", "old", "version",
        "document", "policy", "guideline", "guidelines", "clause", "section",
        "unit", "units", "setup", "set", "up", "beneficiary", "beneficiaries",
        "applicant", "applicants",
    }

    best = None
    for page in later_pages or []:
        page_text = str(page.get("text") or "")
        if not page_text.strip():
            continue
        tokens_page = set(re.findall(r"[a-z0-9]+", page_text.casefold()))
        if selected_anchor and not all(term in tokens_page for term in selected_anchor):
            continue

        # Sentence-like segments plus adjacent pairs preserve exact page excerpts
        # while tolerating line wraps and PDF extraction fragmentation.
        segments = [
            item.strip() for item in re.split(r"(?<=[.!?;:])\s+|\r?\n+", page_text)
            if item.strip()
        ]
        windows = list(segments)
        windows.extend(segments[i] + " " + segments[i + 1] for i in range(len(segments) - 1))
        if not windows:
            windows = [page_text.strip()]

        for snippet in windows:
            candidate_tokens = set(re.findall(r"[a-z0-9]+", snippet.casefold()))
            if selected_anchor and not all(term in candidate_tokens for term in selected_anchor):
                continue
            overlap = {
                term for term in (source_tokens - stop)
                if len(term) >= 3 and term in candidate_tokens
            }
            if selected_anchor:
                score = 10.0 + len(overlap)
            else:
                if len(overlap) < 3:
                    continue
                score = float(len(overlap))
            if re.search(r"\b(no|not|optional|exempt|waived)\b.{0,50}\b(mandatory|required|compulsory)\b", snippet, re.I):
                score += 0.25  # Still related; the changed condition needs human interpretation.
            if best is None or score > best["score"]:
                quote = snippet.strip()
                if len(quote) > 520:
                    quote = quote[:517].rsplit(" ", 1)[0] + "..."
                best = {
                    "page": page.get("page"),
                    "quote": quote,
                    "score": score,
                    "anchor": " ".join(selected_anchor) if selected_anchor else None,
                }
    return best


def _strict_removed_change_gate(change, later_pages):
    # Never allow an AI-generated removal to pass as a confirmed repeal.
    if str(change.get("change_type", "")).casefold() != "removed":
        return change

    # A removed provision always remains human-reviewable, even when the quoted
    # old text is perfectly verified.
    change["review_required"] = True
    related = _strict_later_subject_passage(change, later_pages)
    if related and isinstance(related.get("page"), int) and related.get("quote"):
        change["change_type"] = "modified"
        change["new_page"] = related["page"]
        change["new_quote"] = related["quote"]
        explanation = str(change.get("explanation") or "").strip()
        note = (
            "Related subject matter was found in the later version on page "
            f"{related['page']}. This is a provisional modification, not a confirmed repeal; "
            "a human must compare the complete provisions and conditions."
        )
        change["explanation"] = (explanation + " " if explanation else "") + note
        change["removal_verification"] = {
            "status": "related_later_provision_found",
            "related_page": related["page"],
            "related_quote": related["quote"],
            "subject_anchor": related["anchor"],
            "interpretation": "provisional_modification_requires_human_review",
        }
        change["evidence_warning"] = (
            "Related text exists in the later version. Review both full provisions; do not "
            "treat the earlier requirement as repealed based on this automated comparison."
        )
    else:
        change["removal_verification"] = {
            "status": "not_established",
            "interpretation": "absence_of_match_is_not_proof_of_repeal",
        }
        change["evidence_warning"] = (
            "The automated check did not locate a corresponding later passage. This does not "
            "prove repeal. Review the complete policy, annexes and any renumbered provisions."
        )
    return change


def _deduplicate_changes(
    changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []

    for change in changes:
        fingerprint = (
            str(change.get("change_type", "")),
            normalize_text(change.get("title", "")),
            normalize_text(change.get("old_quote", "")),
            normalize_text(change.get("new_quote", "")),
        )

        if fingerprint in seen:
            continue

        seen.add(fingerprint)
        deduped.append(change)

    return deduped


def _preflight_warnings(
    earlier: dict[str, Any],
    later: dict[str, Any],
    diff: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []

    if earlier.get("sha256") and earlier.get("sha256") == later.get("sha256"):
        warnings.append(
            "The two uploaded PDF files are byte-for-byte identical; "
            "no document change can be established."
        )

    if (
        diff["sequence_similarity"] < 0.08
        and diff["old_unit_count"] > 0
        and diff["new_unit_count"] > 0
    ):
        warnings.append(
            "The documents have very low lexical overlap. Confirm that "
            "they are earlier and later versions of the same policy."
        )

    if diff.get("candidates_truncated"):
        warnings.append(
            "The deterministic candidate storage limit was reached; "
            "some candidate differences were not retained."
        )

    for role, doc in (("earlier", earlier), ("later", later)):
        if doc.get("empty_pages"):
            warnings.append(
                f"The {role} PDF has pages without extracted text "
                f"({', '.join(map(str, doc['empty_pages']))}); "
                "changes on those pages may be missed."
            )

    return warnings


def _global_numeric_warnings(
    result: dict[str, Any],
    earlier: dict[str, Any],
    later: dict[str, Any],
) -> list[str]:
    source_text = " ".join(
        str(page.get("text") or "")
        for doc in (earlier, later)
        for page in doc["pages"]
    )

    narrative_parts = [
        str(result.get("executive_summary") or ""),
        *[str(x) for x in result.get("key_findings", [])],
    ]

    unsupported = _numeric_facts(" ".join(narrative_parts)) - _numeric_facts(
        source_text
    )

    if unsupported:
        return [
            "The executive summary or key findings contain numerical "
            "claims not found in either source PDF: "
            + ", ".join(sorted(unsupported)[:10])
        ]

    return []



def _validate_removal_against_complete_later_document(
    change: dict[str, Any],
    later_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compatibility wrapper for the generalized full-document subject search."""
    if str(change.get("change_type", "")).casefold() != "removed":
        return change
    result = _reconcile_change_pairing(change, [], later_pages)
    verification = result.get("removal_verification") or {}
    verification.setdefault("search_scope", "all_extracted_later_document_pages")
    verification.setdefault("confirmed_repeal", False)
    result["removal_verification"] = verification
    return result



def run_analysis_job(
    analysis_id: str,
    earlier_id: str,
    later_id: str,
) -> None:
    try:
        earlier = database.get_document(earlier_id)
        later = database.get_document(later_id)

        if not earlier or not later:
            raise RuntimeError(
                "One or both source documents could not be found."
            )

        if earlier_id == later_id:
            raise RuntimeError("Choose two different documents for comparison.")

        diff = build_deterministic_diff(
            earlier["pages"],
            later["pages"],
        )

        preflight_warnings = _preflight_warnings(
            earlier, later, diff
        )

        same_file = bool(
            earlier.get("sha256")
            and earlier.get("sha256") == later.get("sha256")
        )

        same_extracted_text = (
            diff["candidate_count"] == 0
            and diff["sequence_similarity"] == 1.0
        )

        if same_file or same_extracted_text:
            if same_file:
                summary = (
                    "The uploaded PDFs are byte-for-byte identical. "
                    "There are no differences to report."
                )
                title = "Identical documents"
            else:
                summary = (
                    "No differences were detected in the extracted selectable "
                    "text. Inspect the originals for visual, image, metadata "
                    "or layout-only changes."
                )
                title = "No extracted text changes detected"

            result = {
                "document_title": title,
                "executive_summary": summary,
                "key_findings": [],
                "changes": [],
                "action_checklist": [],
                "limitations": preflight_warnings,
                "overall_review_required": True,
            }
        else:
            draft = analyse_documents(earlier, later, diff)
            result = draft.model_dump(mode="json")

        enriched_changes = []

        for change in _deduplicate_changes(result.get("changes", [])):
            change = _reconcile_change_pairing(
                change,
                earlier["pages"],
                later["pages"],
            )
            # AI rationale can refer to the pre-reconciliation sentence pair.
            # If its topic anchors contradict the actual source pair, replace
            # it with source-grounded wording rather than displaying stale claims.
            old_pair_text = str(change.get("old_quote") or change.get("old_text") or "")
            new_pair_text = str(change.get("new_quote") or change.get("new_text") or "")
            pair_anchors = _pair_topic_anchors(old_pair_text) | _pair_topic_anchors(new_pair_text)
            explanation_anchors = _pair_topic_anchors(str(change.get("explanation") or ""))
            if pair_anchors and explanation_anchors and not (pair_anchors & explanation_anchors):
                _neutralize_repaired_pair_explanation(change)
                if "inheritance_transfer" in pair_anchors:
                    change["title"] = "Inheritance-related land transfer provision"
                elif "eligibility_cutoff" in pair_anchors:
                    change["title"] = "Eligibility cut-off provision"
                elif "physical_verification" in pair_anchors:
                    change["title"] = "Physical verification provision"
                elif "edp_training" in pair_anchors:
                    change["title"] = "EDP training provision"
                elif "udyam_registration" in pair_anchors:
                    change["title"] = "Udyam registration provision"
            pairing = change.get("pairing_verification") or {}
            pairing_verified = bool(pairing.get("pairing_verified"))
            change["pairing_verified"] = pairing_verified
            change["pairing_status"] = pairing.get("status", "not_assessed")
            # Source quotation matching and provision correspondence are
            # independent facts. Neither one alone validates legal meaning.
            change["interpretation_verified"] = False
            change["interpretation_status"] = "ai_interpretation_not_human_verified"
            requires_old, requires_new = _required_evidence(change)

            old_page = change.get("old_page")
            new_page = change.get("new_page")
            old_quote = str(change.get("old_quote") or "")
            new_quote = str(change.get("new_quote") or "")
            old_text = str(change.get("old_text") or "")
            new_text = str(change.get("new_text") or "")

            if requires_old:
                old_quote_ok = _quote_exists(
                    earlier["pages"], old_page, old_quote
                )
                old_excerpt_ok = _excerpt_exists(
                    earlier["pages"], old_page, old_text
                )
                old_verified = old_quote_ok and old_excerpt_ok
            else:
                old_quote_ok = old_page is None and not old_quote
                old_excerpt_ok = not old_text.strip()
                old_verified = None

            if requires_new:
                new_quote_ok = _quote_exists(
                    later["pages"], new_page, new_quote
                )
                new_excerpt_ok = _excerpt_exists(
                    later["pages"], new_page, new_text
                )
                new_verified = new_quote_ok and new_excerpt_ok
            else:
                new_quote_ok = new_page is None and not new_quote
                new_excerpt_ok = not new_text.strip()
                new_verified = None

            evidence_verified = (
                old_quote_ok
                and old_excerpt_ok
                and new_quote_ok
                and new_excerpt_ok
            )

            consistency_warnings = _change_consistency_warnings(change)
            numerical_verified = not consistency_warnings
            context_warnings = _possible_excerpt_context_warnings(change)
            if consistency_warnings:
                _neutralize_unsupported_explanation(change, consistency_warnings)

            change["change_id"] = f"CHG-{len(enriched_changes) + 1:03d}"
            change["old_evidence_verified"] = old_verified
            change["new_evidence_verified"] = new_verified
            change["old_text_verified"] = (
                old_excerpt_ok if requires_old else None
            )
            change["new_text_verified"] = (
                new_excerpt_ok if requires_new else None
            )
            # Keep the legacy field for compatibility, but define it explicitly as
            # source-quotation/page verification—not clause pairing or legal validation.
            both_sides_verified = bool(
                requires_old and requires_new and old_verified is True and new_verified is True
            )
            one_sided_quote_verified = bool(
                (requires_old != requires_new) and evidence_verified
            )
            change["source_quote_verified"] = bool(evidence_verified)
            change["both_sides_verified"] = both_sides_verified
            change["evidence_completeness"] = (
                "two_sided_quotes_verified" if both_sides_verified
                else "one_sided_quote_verified" if one_sided_quote_verified
                else "source_quote_needs_review"
            )
            change["evidence_verified"] = bool(evidence_verified)
            if both_sides_verified:
                change["evidence_status"] = "both_source_quotes_matched"
            elif one_sided_quote_verified:
                change["evidence_status"] = "one_sided_source_quote_matched"
            else:
                change["evidence_status"] = "source_quote_or_page_needs_review"
            change["source_quote_match_status"] = change["evidence_status"]
            # Do not let a page-level quote match silently imply that old/new
            # clauses are about the same subject.
            change["pairing_verified"] = bool(
                (change.get("pairing_verification") or {}).get("pairing_verified")
            )
            change["pairing_status"] = (
                change.get("pairing_verification") or {}
            ).get("status", "not_assessed")
            change["interpretation_verified"] = False
            change["interpretation_status"] = "ai_interpretation_not_human_verified"
            change["numerical_consistency_verified"] = numerical_verified
            change["consistency_warnings"] = consistency_warnings
            change["context_warnings"] = context_warnings
            change["source_context_status"] = (
                "possible_fragment" if context_warnings else "excerpt_boundary_not_flagged"
            )

            change["review_required"] = (
                bool(change.get("review_required"))
                or not evidence_verified
                or not numerical_verified
                or bool(context_warnings)
            )

            warnings = []

            if not evidence_verified:
                warnings.append(
                    "A required source quote or excerpt is missing, "
                    "does not match the cited page, or uses an invalid "
                    "source page. Verify the finding manually."
                )

            warnings.extend(consistency_warnings)
            warnings.extend(context_warnings)

            pairing = change.get("pairing_verification") or {}
            if not pairing.get("pairing_verified"):
                pairing_status = pairing.get("status", "not_assessed")
                if pairing_status == "unrelated_old_new_pair_rejected":
                    warnings.append(
                        "The earlier excerpt concerns a different subject from the later excerpt "
                        "and was detached from this finding."
                    )
                warnings.append(
                    "The source quotation may match its cited page, but correspondence between "
                    "the earlier and later provisions was not established "
                    f"(pairing status: {pairing_status}). Treat this as a provisional candidate "
                    "and review the complete relevant sections."
                )
            elif not change.get("interpretation_verified", False):
                warnings.append(
                    "The source pair passed automated subject-correspondence checks; "
                    "the policy/legal interpretation has not been independently verified by a human."
                )

            change["evidence_warning"] = " ".join(warnings)
            if not evidence_verified or not numerical_verified:
                change["confidence"] = "low"

            enriched_changes.append(change)

        enriched_changes, suppressed_findings = _suppress_non_material_and_duplicate_findings(enriched_changes)
        result["changes"] = enriched_changes
        result["suppressed_findings"] = suppressed_findings
        result["suppressed_findings_count"] = len(suppressed_findings)
        if suppressed_findings:
            prior_summary = str(result.get("executive_summary") or "").strip()
            result["executive_summary"] = (
                f"Source reconciliation retained {len(enriched_changes)} distinct candidate finding(s) "
                f"and suppressed {len(suppressed_findings)} candidate(s) as likely restatements, duplicates, "
                "or incomplete fragments. Suppressed items are listed separately for auditability. "
                + prior_summary
            ).strip()
        # Key findings must reflect the reportable findings after false-positive
        # and duplicate suppression, not the model's pre-validation narrative.
        result["key_findings"] = [
            f"{item.get('title', 'Finding')}: {item.get('explanation', '')}".strip()
            for item in enriched_changes[:8]
        ]
        if any(bool(item.get("review_required")) for item in enriched_changes) or suppressed_findings:
            result["overall_review_required"] = True

        # Rebuild from the reconciled reportable findings. Never retain AI actions
        # that may refer to a suppressed candidate or an unrelated passage.
        enriched_actions = _build_final_action_checklist(
            enriched_changes, earlier, later
        )
        result["action_checklist"] = enriched_actions

        global_numeric_warnings = _global_numeric_warnings(
            result, earlier, later
        )

        result["limitations"] = list(dict.fromkeys(
            (result.get("limitations") or [])
            + preflight_warnings
            + global_numeric_warnings
        ))

        if preflight_warnings or global_numeric_warnings:
            result["overall_review_required"] = True

        if any(
            not item["evidence_verified"]
            or not item["numerical_consistency_verified"]
            for item in enriched_changes
        ):
            result["overall_review_required"] = True

        if any(
            item.get("source_verified") is False
            for item in enriched_actions
        ):
            result["overall_review_required"] = True

        result["document_metadata"] = {
            "earlier": {
                "document_id": earlier["document_id"],
                "filename": earlier["filename"],
                "title": earlier["title"],
                "page_count": earlier["page_count"],
                "sha256": earlier.get("sha256", ""),
            },
            "later": {
                "document_id": later["document_id"],
                "filename": later["filename"],
                "title": later["title"],
                "page_count": later["page_count"],
                "sha256": later.get("sha256", ""),
            },
        }

        result["comparison_metadata"] = {
            key: value for key, value in diff.items()
            if key != "candidates"
        }
        result["comparison_metadata"]["preflight_warnings"] = (
            preflight_warnings
        )
        if result.get("candidate_review_metadata"):
            result["comparison_metadata"]["candidate_review_metadata"] = (
                result["candidate_review_metadata"]
            )

        result["counts"] = {
            "total": len(enriched_changes),
            # evidence_verified remains as a backwards-compatible alias for
            # source quote/page matching only. These counters make its scope explicit.
            "evidence_verified": sum(
                1 for item in enriched_changes
                if item.get("source_quote_verified") is True
            ),
            "source_quotes_verified": sum(
                1 for item in enriched_changes
                if item.get("source_quote_verified") is True
            ),
            "both_sides_verified": sum(
                1 for item in enriched_changes
                if item.get("both_sides_verified") is True
            ),
            "one_sided_quotes_verified": sum(
                1 for item in enriched_changes
                if item.get("evidence_completeness") == "one_sided_quote_verified"
            ),
            "interpretation_verified": sum(
                1 for item in enriched_changes
                if item.get("interpretation_verified") is True
            ),
            "context_warnings": sum(
                1 for item in enriched_changes
                if bool(item.get("context_warnings"))
            ),
            "numerically_consistent": sum(
                1 for item in enriched_changes
                if item["numerical_consistency_verified"]
            ),
            "needs_review": sum(
                1 for item in enriched_changes
                if item["review_required"]
            ),
            "pairing_verified": sum(
                1 for item in enriched_changes if item.get("pairing_verified") is True
            ),
            "pairing_unverified": sum(
                1 for item in enriched_changes if item.get("pairing_verified") is not True
            ),
            "suppressed": len(suppressed_findings),
            "by_type": {
                change_type: sum(
                    1 for item in enriched_changes
                    if item.get("change_type") == change_type
                )
                for change_type in sorted({
                    item.get("change_type", "other")
                    for item in enriched_changes
                })
            },
        }

        database.update_analysis_completed(analysis_id, _enforce_persisted_review_invariants(result))

    except Exception as exc:
        message = str(exc).strip() or "Analysis failed. Please try again."
        database.update_analysis_failed(analysis_id, message[:900])

def _enforce_persisted_review_invariants(payload):
    import json

    was_json_text = isinstance(payload, str)
    if was_json_text:
        try:
            data = json.loads(payload)
        except Exception:
            return payload
    elif hasattr(payload, "model_dump"):
        data = payload.model_dump()
    else:
        data = payload

    if not isinstance(data, (dict, list)):
        return payload

    containers = []
    seen = set()

    def visit(value):
        marker = id(value)
        if marker in seen:
            return
        if isinstance(value, dict):
            seen.add(marker)
            changes = value.get("changes")
            if isinstance(changes, list):
                containers.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            seen.add(marker)
            for child in value:
                if isinstance(child, (dict, list)):
                    visit(child)

    visit(data)
    if not containers:
        return payload

    for container in containers:
        changes = container.get("changes") or []
        for change in changes:
            if not isinstance(change, dict):
                continue
            if str(change.get("change_type", "")).casefold() == "removed":
                change["review_required"] = True
                note = (
                    "Automated removal is not proof of repeal. A human reviewer must "
                    "compare the complete later policy, including renumbered clauses, "
                    "annexes and related provisions, before treating this as removed."
                )
                existing = str(change.get("evidence_warning") or "").strip()
                if note not in existing:
                    change["evidence_warning"] = (existing + " " if existing else "") + note
                change["removal_verification"] = {
                    "status": "human_review_required",
                    "confirmed_repeal": False,
                }

            pairing = change.get("pairing_verification")
            if isinstance(pairing, dict) and pairing.get("pairing_verified") is False:
                change["review_required"] = True
                note = (
                    "Earlier/later clause correspondence was not established. "
                    "A matched quotation is not proof that the two excerpts concern the same provision."
                )
                existing = str(change.get("evidence_warning") or "").strip()
                if note not in existing:
                    change["evidence_warning"] = (existing + " " if existing else "") + note

            addition = change.get("addition_verification")
            if isinstance(addition, dict) and addition.get("confirmed_addition") is not True:
                change["review_required"] = True

            removal = change.get("removal_verification")
            if isinstance(removal, dict) and removal.get("confirmed_repeal") is not True:
                change["review_required"] = True

        review_metadata = container.get("candidate_review_metadata")
        if not isinstance(review_metadata, dict):
            comparison_metadata = container.get("comparison_metadata")
            review_metadata = (
                comparison_metadata.get("candidate_review_metadata", {})
                if isinstance(comparison_metadata, dict) else {}
            )
        detected = review_metadata.get("detected_candidates")
        reviewed = review_metadata.get("reviewed_candidates")
        if (
            isinstance(detected, int) and isinstance(reviewed, int)
            and reviewed < detected
        ):
            container["overall_review_required"] = True
            limitations = container.get("limitations")
            if not isinstance(limitations, list):
                limitations = []
                container["limitations"] = limitations
            note = (
                f"AI reviewed {reviewed} of {detected} detected candidates. "
                "This is not an exhaustive comparison; remaining candidates require review."
            )
            if note not in limitations:
                limitations.append(note)

        # Persisted actions must map one-to-one to retained report findings.
        retained_ids = {
            str(item.get("change_id")) for item in changes
            if isinstance(item, dict) and item.get("change_id")
        }
        actions = container.get("action_checklist")
        if isinstance(actions, list):
            safe_actions = []
            seen_action_findings = set()
            for action in actions:
                if not isinstance(action, dict):
                    continue
                linked_id = str(action.get("change_id") or "")
                if linked_id not in retained_ids or linked_id in seen_action_findings:
                    continue
                action["review_required"] = True
                seen_action_findings.add(linked_id)
                safe_actions.append(action)
            container["action_checklist"] = safe_actions

        required = sum(
            1 for item in changes
            if isinstance(item, dict) and bool(item.get("review_required"))
        )
        counts = container.get("counts")
        if not isinstance(counts, dict):
            counts = {}
            container["counts"] = counts
        counts["needs_review"] = required
        if required or any(
            isinstance(item, dict) and item.get("change_type") == "removed"
            for item in changes
        ):
            container["overall_review_required"] = True

    if was_json_text:
        return json.dumps(data, ensure_ascii=False)
    return data

