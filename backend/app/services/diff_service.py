"""Deterministic, page-aware provision alignment.

This service creates candidate changes only. It does not determine legal meaning.
All candidates retain the original PDF page number and source wording.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def normalize_text(value: str) -> str:
    """Normalize extracted text for comparison, never for source display."""
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u00a0", " ").replace("\u202f", " ")
    value = value.replace("\u2011", "-").replace("\u00ad", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip().casefold()


def _units_from_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []

    for page in pages:
        page_number = int(page.get("page", 0))
        text = str(page.get("text") or "")
        fragments = _SENTENCE_BOUNDARY.split(text)
        pending = ""

        for fragment in fragments:
            fragment = re.sub(r"\s+", " ", fragment).strip()
            if not fragment:
                continue

            if len(fragment) < 12:
                pending = f"{pending} {fragment}".strip()
                continue

            if pending:
                fragment = f"{pending} {fragment}".strip()
                pending = ""

            if len(fragment) >= 12:
                units.append({
                    "page": page_number,
                    "text": fragment[:1800],
                })

        if pending and len(pending) >= 12:
            units.append({"page": page_number, "text": pending[:1800]})

    return units


def build_deterministic_diff(
    earlier_pages: list[dict[str, Any]],
    later_pages: list[dict[str, Any]],
    *,
    max_candidates: int = 2500,
) -> dict[str, Any]:
    """Align sentence-like units and preserve page provenance.

    Counts describe the complete alignment, even when the stored candidate
    list reaches its safety cap.
    """
    old_units = _units_from_pages(earlier_pages)
    new_units = _units_from_pages(later_pages)

    old_keys = [normalize_text(item["text"]) for item in old_units]
    new_keys = [normalize_text(item["text"]) for item in new_units]

    matcher = SequenceMatcher(
        a=old_keys,
        b=new_keys,
        autojunk=False,
    )

    candidates: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "modified": 0}
    total_candidate_count = 0
    max_candidates = max(1, int(max_candidates))

    def append_candidate(
        operation: str,
        old_item: dict[str, Any] | None,
        new_item: dict[str, Any] | None,
        similarity: float | None = None,
    ) -> None:
        nonlocal total_candidate_count

        total_candidate_count += 1
        counts[operation] += 1

        if len(candidates) >= max_candidates:
            return

        candidates.append({
            "operation": operation,
            "old_page": old_item["page"] if old_item else None,
            "old_text": old_item["text"][:900] if old_item else "",
            "new_page": new_item["page"] if new_item else None,
            "new_text": new_item["text"][:900] if new_item else "",
            "alignment_similarity": (
                round(similarity, 4) if similarity is not None else None
            ),
        })

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        old_slice = old_units[i1:i2]
        new_slice = new_units[j1:j2]

        if tag == "replace":
            remaining_new = set(range(len(new_slice)))

            for old_index, old_item in enumerate(old_slice):
                best_index = None
                best_ratio = 0.0

                if len(old_slice) * len(new_slice) <= 10000:
                    search_indices = remaining_new
                else:
                    expected = round(
                        old_index * max(len(new_slice) - 1, 0)
                        / max(len(old_slice) - 1, 1)
                    )
                    search_indices = sorted(
                        remaining_new,
                        key=lambda idx: abs(idx - expected),
                    )[:20]

                old_key = normalize_text(old_item["text"])

                for new_index in search_indices:
                    ratio = SequenceMatcher(
                        None,
                        old_key,
                        normalize_text(new_slice[new_index]["text"]),
                        autojunk=False,
                    ).ratio()

                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_index = new_index

                if best_index is not None and best_ratio >= 0.30:
                    append_candidate(
                        "modified",
                        old_item,
                        new_slice[best_index],
                        best_ratio,
                    )
                    remaining_new.remove(best_index)
                else:
                    append_candidate("removed", old_item, None)

            for new_index in sorted(remaining_new):
                append_candidate("added", None, new_slice[new_index])

        elif tag == "delete":
            for item in old_slice:
                append_candidate("removed", item, None)

        elif tag == "insert":
            for item in new_slice:
                append_candidate("added", None, item)

    old_chars = sum(len(str(page.get("text") or "")) for page in earlier_pages)
    new_chars = sum(len(str(page.get("text") or "")) for page in later_pages)

    old_tokens = set(re.findall(r"[\w]+", " ".join(old_keys)))
    new_tokens = set(re.findall(r"[\w]+", " ".join(new_keys)))
    token_union = old_tokens | new_tokens

    lexical_overlap = (
        len(old_tokens & new_tokens) / len(token_union)
        if token_union else 1.0
    )

    return {
        "method": "page-aware sentence alignment with Unicode-normalized token diagnostics",
        "old_unit_count": len(old_units),
        "new_unit_count": len(new_units),
        "sequence_similarity": round(lexical_overlap, 4),
        "exact_unit_sequence_ratio": round(matcher.ratio(), 4),
        "candidate_count": len(candidates),
        "total_candidate_count": total_candidate_count,
        "candidate_limit": max_candidates,
        "candidates_truncated": total_candidate_count > len(candidates),
        "added_candidate_count": counts["added"],
        "removed_candidate_count": counts["removed"],
        "modified_candidate_count": counts["modified"],
        "earlier_characters": old_chars,
        "later_characters": new_chars,
        "candidates": candidates,
    }
