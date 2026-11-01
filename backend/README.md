# Policy Intelligence Engine — Backend v0.4.3

FastAPI backend for page-preserving policy-PDF ingestion and evidence-grounded comparison. This submission snapshot combines the v0.4.1 evidence/candidate-recall base, v0.4.2 false-positive reconciliation, and v0.4.3 integrity hardening.

## Quick start (Windows PowerShell)

```powershell
Set-Location .ackend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Ollama must be running locally and the configured model must already be pulled. The default example uses `qwen3.5:4b-q8_0`. Keep `.env` private. For a faster hackathon demo, the configured review limit is 64; the report must disclose the selected and detected candidate counts. Do not describe bounded review as exhaustive.

Health: `http://127.0.0.1:8001/health`  
API docs: `http://127.0.0.1:8001/docs`

## API workflow

1. `POST /api/documents/upload` with multipart `file` and `version=earlier|later`.
2. `GET /api/documents` or `GET /api/documents/{document_id}` to confirm uploads.
3. `POST /api/documents/compare` with `earlier_document_id` and `later_document_id`.
4. Poll `GET /api/analysis/{analysis_id}` until `completed` or `failed`.
5. `GET /api/analysis/{analysis_id}/changes` returns the findings and counts.

PDF page numbers are 1-based.

## v0.4.3 integrity semantics

- `source_quote_verified`: the available quotation was located on its cited extracted PDF page.
- `both_sides_verified`: both quotations required for a two-sided finding matched their cited pages.
- `pairing_verified`: an automated subject-correspondence guardrail passed. It is not a legal-equivalence test.
- `interpretation_verified`: remains false until a qualified human reviewer validates the substantive legal/policy effect.
- `review_required`: keeps ambiguous, one-sided, partial-coverage, numerical, pairing and removal cases visible for human review.
- Every action has an `action_id` and `change_id`; actions are derived from retained findings after reconciliation. Suppressed candidates cannot generate actions.
- Unsupported numeric/date/frequency claims in explanations are neutralized and recorded in `explanation_validation`.
- Incomplete source snippets receive `context_warnings` / `source_context_status` rather than being treated as complete clauses.

## Test

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m pytest -q
```

The team Windows installer log reported 87 tests passed. The reconstructed v0.4.3 source snapshot in this handoff was also independently compiled and tested: 87 tests passed in 0.78 seconds.

## Important limitations

This is a local decision-support prototype, not legal advice, a compliance determination or a substitute for manual policy review. Lexical/topic pairing is a retrieval/guardrail step, not legal equivalence. A matching quote proves location, not interpretation. Absence from the later PDF does not prove repeal. Scanned/image-only PDFs, complex visual tables, authentication, role-based access, production job queues and hosted monitoring are not comprehensively supported. Keep the API bound to localhost during the demo; do not expose sensitive policy documents on a public network.
