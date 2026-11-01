import { useMemo, useState } from 'react'
import AnalysisTabs from './AnalysisTabs'

const filters = [
  ['all', 'All findings'], ['added', 'Added'], ['removed', 'Removed'], ['modified', 'Modified'],
  ['eligibility', 'Eligibility'], ['deadline', 'Deadline'], ['process', 'Process'],
  ['fee', 'Fees'], ['document_requirement', 'Documents'], ['clarification', 'Clarification'],
]

function Verification({ change }) {
  if (change.evidence_verified === true) return <span className="status-pill verified">Evidence verified</span>
  if (change.evidence_verified === false) return <span className="status-pill warning">Evidence needs review</span>
  return <span className="status-pill neutral">Evidence status unavailable</span>
}

function ChangeCard({ change, index }) {
  const type = String(change.change_type || 'other').replaceAll('_', ' ')
  const oldQuote = change.old_quote || change.old_text || ''
  const newQuote = change.new_quote || change.new_text || ''
  return (
    <article className="change-row">
      <div className="change-heading">
        <div><span className="change-id">{change.change_id || `CHANGE ${String(index + 1).padStart(3, '0')}`}</span><h2>{change.title || 'Untitled change'}</h2></div>
        <span className={`change-type type-${String(change.change_type || 'other').replaceAll('_', '-')}`}>{type}</span>
      </div>
      <div className="change-meta"><Verification change={change} />{change.review_required && <span className="status-pill warning">Human review required</span>}{change.confidence && <span className="status-pill neutral">Confidence: {change.confidence}</span>}</div>
      <div className="text-comparison">
        <div><h3>Earlier version {change.old_page != null ? `· PDF page ${change.old_page}` : ''}</h3><p>{oldQuote || 'No earlier passage is attached to this finding.'}</p>{change.old_evidence_verified === true && <small>Quotation found on cited page</small>}</div>
        <div><h3>Later version {change.new_page != null ? `· PDF page ${change.new_page}` : ''}</h3><p>{newQuote || 'No later passage is attached to this finding.'}</p>{change.new_evidence_verified === true && <small>Quotation found on cited page</small>}</div>
      </div>
      {change.explanation && <p className="change-explanation">{change.explanation}</p>}
      {Array.isArray(change.affected_stakeholders) && change.affected_stakeholders.length > 0 && <p className="stakeholder-line"><strong>Potentially affected:</strong> {change.affected_stakeholders.join(' · ')}</p>}
      {change.practical_action && <p className="action-callout"><strong>Suggested action:</strong> {change.practical_action}</p>}
      {change.evidence_warning && <p className="inline-warning">{change.evidence_warning}</p>}
      {Array.isArray(change.consistency_warnings) && change.consistency_warnings.map((warning, i) => <p className="inline-warning" key={i}>{warning}</p>)}
    </article>
  )
}

function Changes({ bundle, onBack, onOverview, onImpact, onEvidence }) {
  const [activeFilter, setActiveFilter] = useState('all')
  const changes = Array.isArray(bundle?.result?.changes) ? bundle.result.changes : []
  const visibleChanges = useMemo(() => changes.filter((change) => activeFilter === 'all' || change.change_type === activeFilter), [changes, activeFilter])

  return (
    <main className="main-content changes-page">
      <button type="button" className="back-button" onClick={onBack}>← Back to workspace</button>
      <div className="eyebrow">ANALYSIS FINDINGS</div>
      <h1>Detected changes</h1>
      <p className="description">Findings below are loaded from the completed backend analysis. Review each source passage and its verification status.</p>
      <AnalysisTabs active="changes" onOverview={onOverview} onImpact={onImpact} onEvidence={onEvidence} />
      <div className="change-filters" aria-label="Filter changes">
        {filters.map(([value, label]) => <button key={value} type="button" className={`filter-button ${activeFilter === value ? 'selected' : ''}`} aria-pressed={activeFilter === value} onClick={() => setActiveFilter(value)}>{label}</button>)}
      </div>
      <p className="results-count">Showing {visibleChanges.length} of {changes.length} backend findings</p>
      {visibleChanges.length === 0 ? <div className="empty-results">No backend findings match this filter.</div> : <div className="changes-list">{visibleChanges.map((change, index) => <ChangeCard key={change.change_id || `${change.title}-${index}`} change={change} index={index} />)}</div>}
      <p className="legal-note">A source quotation being present does not by itself prove the interpretation is legally correct.</p>
    </main>
  )
}

export default Changes
