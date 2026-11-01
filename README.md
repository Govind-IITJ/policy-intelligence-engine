# Policy Intelligence Engine v0.4.3 — Hackathon Submission

**Theme:** Civic Pulse · Digital Governance & Public Information  
**Product experience:** Policy Quest  
**Purpose:** Compare earlier and later government-policy PDFs, surface candidate changes, connect each finding to source pages and show what remains uncertain.

## What it does

1. Ingests two PDF versions and extracts selectable text page by page.
2. Aligns sentence-like units deterministically and generates addition/removal/modification candidates.
3. Sends a ranked, bounded set to a local Ollama model for compact classification.
4. Reattaches source passages and page references deterministically.
5. Applies quotation checks, candidate-pairing guardrails, numerical consistency checks, false-positive suppression and conservative addition/removal handling.
6. Produces a report in Policy Quest: Mission Hub, Change Arena, People Map and Evidence Vault.

## What changed in v0.4.3

- Rebuilds the final action checklist from retained findings only; each action has `action_id` and `change_id`.
- Separates source quote matching, two-sided evidence, automated pairing and human interpretation.
- Neutralizes unsupported numerical/date/frequency claims in AI explanations.
- Marks short source snippets as possible fragments.
- Exposes verification states and finding links in the frontend.
- Keeps v0.4.2's suppression ledger for clear restatements, duplicates and incomplete fragments.

## Stack

React 19 + Vite 8 · FastAPI · PyMuPDF · SQLite · Ollama/Qwen · pytest.

## Quick demo

1. Run the root `FINAL_HACKATHON_LAUNCH_v0.4.3.ps1` helper on the team's Windows machine.
2. Confirm `/health` reports version `0.4.3`.
3. Open `http://localhost:5173` and upload the official 2018 and revised 2020 PM-KISAN guideline PDFs as Earlier and Later.
4. Show candidate coverage, retained/suppressed findings, one source-linked change, stakeholder tags and Evidence Vault.
5. Explicitly state the current review count and that human review is required for legal interpretation.

The launcher sets the quick-demo review cap to 64 so a local model can finish sooner. This is bounded review, not exhaustive review. The full-coverage setting (451) is provided separately, but can take materially longer and is not recommended immediately before a timed judging demo.

## Validation evidence and status

- Team ran the v0.4.3 installer on Windows: Python compilation passed and **87 backend tests passed**.
- A prior PM-KISAN analysis (analysis ID `ce06d104-de52-47ab-81ba-50bc5c66a5e8`, generated before v0.4.3) detected 451 candidates, reviewed 64 across four successful batches, retained 5 candidates and suppressed 7. The result is included as historical diagnostic evidence, not as a v0.4.3 live acceptance result.
- In that prior analysis, all 5 retained quotations were marked source-verified, but only 1/5 pairings passed automated correspondence checks and 5/5 findings required human review. The substantive policy interpretations were not human-verified.
- The v0.4.3 fresh live PM-KISAN acceptance run and frontend production build were not confirmed in the supplied Windows logs. The reconstructed backend source was independently compiled and passed 87 tests in the packaging environment. The launch helper starts the installed backend, attempts the local frontend production build, then starts Policy Quest. Do not claim the live PM-KISAN run or frontend build passed unless the local output confirms them.

## Safety and limitations

This tool is policy-review decision support, not legal advice or an automatic compliance system. A matched quotation proves that text is on a cited page, not that a model's explanation is correct. Automated pairing is not legal equivalence. Missing counterpart text does not prove a new rule or repeal. Candidate coverage can be partial. Scanned PDFs, images, complex tables, production auth/access control, public hosting and robust job queuing are outside this prototype's verified scope.

## Team roles

- Backend / AI: document ingestion, candidate comparison, model orchestration, evidence and integrity controls.
- Research: official scheme source selection and manual provision validation.
- Frontend: Policy Quest workflow and report exploration.
