# Architecture, Validation & Safety — v0.4.3

## Pipeline

| Stage | Component | Output | Boundary |
|---|---|---|---|
| Ingestion | FastAPI + PyMuPDF | File metadata, extracted text per page | Reject invalid PDF; preserve 1-based page numbers |
| Alignment | Deterministic diff service | Added/removed/modified candidate units | Candidates are navigation aids, not conclusions |
| Candidate review | Ranked Ollama batches | Candidate IDs and concise classification | Bounded coverage is reported explicitly |
| Evidence assembly | Backend candidate map | Exact source snippets and page numbers | Backend attaches evidence rather than asking model to invent citations |
| Reconciliation | Topic/lexical counterpart search + suppression | Paired, provisional and suppressed candidates | Similarity is not legal equivalence |
| Integrity validation | Quote/page, numerical, context, persistence and action guards | Separate verification fields and warnings | Quote presence is not legal correctness |
| Reporting | Policy Quest | Mission Hub, Change Arena, People Map, Evidence Vault | Uncertainty, coverage and review status remain visible |

## Four independent verification concepts

1. **Source quote verified:** available quotation is found on the cited extracted PDF page.
2. **Both sides verified:** both old and new quotes are found where a two-sided finding requires them.
3. **Pairing verified:** automated subject-correspondence checks indicate a plausible relationship. This does not prove legal equivalence.
4. **Interpretation verified:** only a human reviewer can set this after examining full provisions, definitions, exceptions and cross-references. AI output remains unverified by default.

## v0.4.2 reconciliation

Clear restatements and duplicates are suppressed from the substantive finding list, while reasons remain in `suppressed_findings`. In the historical PM-KISAN post-processing input, 5 candidates were retained and 7 suppressed/merged. This was a deterministic post-processing dry run on an existing analysis, not a fresh model run.

## v0.4.3 integrity hardening

- Final action checklist is regenerated from retained findings after suppression.
- Each action references one retained `change_id`; orphan actions are rejected by the acceptance runner.
- Evidence fields distinguish quote location, two-sided match, subject pairing and human interpretation.
- Unsupported numeric/date/frequency claims are neutralized and recorded in `explanation_validation`.
- Fragmentary quotations carry context warnings.

## Security / production boundary

The current prototype is local-development software. It has no verified authentication, per-user authorization, retention controls, malware scanning, public deployment hardening or durable distributed job queue. Keep it on localhost and do not upload confidential personal data for a public demo. Before production, add access control, audited retention/deletion, encrypted storage, request limits, malware checks, background job orchestration and operational monitoring.
