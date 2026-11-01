# Judge Q&A — v0.4.3

**What makes this more than a PDF chatbot?**  
It uses a structured pipeline: page-preserving PDF extraction, deterministic alignment, bounded candidate classification, backend-attached source quotations, counterpart search, false-positive reconciliation and integrity checks. The AI classifies candidates; deterministic backend code attaches source evidence.

**How do you reduce hallucinations?**  
The system checks quote presence on the cited page, separates quote matching from clause pairing and interpretation, validates numbers/frequencies, warns about incomplete fragments and prevents actions from being generated for suppressed findings. These controls reduce risk; they do not guarantee zero hallucinations.

**What did v0.4.3 fix?**  
It rebuilds the action checklist from retained findings, links every action to a change ID, separates source quote/two-sided/pairing/human interpretation states, neutralizes unsupported numeric explanations and flags possible fragments.

**What validation has been completed?**  
The team installer ran on Windows. Python compilation passed and 87 backend tests passed. The prior PM-KISAN result is historical diagnostic evidence from before v0.4.3. A fresh v0.4.3 live-PDF acceptance run and local frontend production build have not yet been confirmed in the submitted logs.

**Why does the report say candidate coverage is partial?**  
The supplied historical PM-KISAN run detected 451 candidate passages but reviewed 64 in four batches. We expose the ratio rather than implying completeness. A full 451-candidate run is available but takes materially longer on a local model.

**What happens when a clause moves or is renumbered?**  
The engine searches the full extracted counterpart document for a plausible matching passage. The match remains provisional; a human must inspect the complete text, definitions and cross-references.

**How are removals treated?**  
Absence of a phrase in a later PDF is not proof of repeal. Removal candidates stay provisional until a reviewer checks the complete later policy, annexes and cross-references.

**Is this legal advice or a compliance engine?**  
No. It is decision support for discovering and reviewing potential policy changes. A human remains responsible for the legal/policy conclusion and any operational action.
