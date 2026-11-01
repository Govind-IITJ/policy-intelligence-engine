# 2 minute 30 second judging demo — v0.4.3

## 0:00–0:20 — Problem
“Government scheme rules are published in long PDFs and revised over time. A reviewer must discover what changed, locate the source wording and determine who may be affected. Policy Intelligence turns two policy versions into a traceable review workflow.”

## 0:20–0:45 — Upload
“Here we compare the 2018 and revised 2020 PM-KISAN operational guidelines. The system extracts text page by page, aligns candidate passages and sends a bounded set of candidates to a local AI model.”

## 0:45–1:15 — Change Arena
“Each retained finding is linked to the earlier and later source text and page. A quote match only verifies the location of text; it does not prove the two clauses are legally equivalent or that the model's interpretation is correct.”

## 1:15–1:40 — People Map / Actions
“Stakeholder tags and proposed actions help a reviewer understand who might be affected. In v0.4.3, actions are generated only from retained findings and each action links back to its finding. They remain review prompts, not automatic compliance instructions.”

## 1:40–2:05 — Evidence Vault / Suppression
“The Evidence Vault separates source-quote matching, two-sided evidence, automated pairing and human interpretation. Unchanged restatements, duplicates and incomplete fragments can be suppressed from the main list, but remain in an auditable suppression ledger.”

## 2:05–2:30 — Honest limitation / close
“Our current PM-KISAN diagnostic reviewed 64 of 451 detected candidates across four successful batches. It is not exhaustive. Every substantive legal interpretation needs a human reviewer. Our goal is to reduce search time and make the evidence trail visible—not to replace policy experts.”

## Demo checklist
- Confirm `/health` reports v0.4.3 before opening the UI.
- Show a real completed result or upload/run the official documents live.
- State the actual candidate coverage displayed by the run; do not call 64/451 exhaustive.
- Do not call quote matching legal verification.
- Do not say an absent clause has been repealed without a human checking the whole later policy.
- Do not invent a live analysis ID or progress. If live AI is slow, explain that the historical run is from the prior build and use it only as a diagnostic example.
