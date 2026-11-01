import AnalysisTabs from './AnalysisTabs'

function AnalysisOverview({ bundle, onBack, onChanges, onImpact, onEvidence }) {
  const data = bundle?.result || {}
  const changes = Array.isArray(data.changes) ? data.changes : []
  const counts = data.counts || {}
  const byType = counts.by_type || {}
  const count = (type) => byType[type] ?? changes.filter((change) => change.change_type === type).length
  const metadata = data.document_metadata || {}
  const earlier = metadata.earlier || bundle?.earlierDocument || {}
  const later = metadata.later || bundle?.laterDocument || {}
  const limitations = Array.isArray(data.limitations) ? data.limitations : []
  const evidenceVerified = counts.evidence_verified ?? changes.filter((change) => change.evidence_verified).length
  const needsReview = counts.needs_review ?? changes.filter((change) => change.review_required).length

  return (
    <main className="main-content analysis-page">
      <button className="back-button" type="button" onClick={onBack}>← Back to workspace</button>
      <div className="eyebrow">COMPLETED ANALYSIS · {bundle.analysisId}</div>
      <h1>Comparison overview</h1>
      <div className="document-pair">
        <div><span className="document-kicker">EARLIER VERSION</span><h2>{earlier.title || earlier.filename || 'Earlier document'}</h2><p>{earlier.filename || ''}</p><span>{earlier.page_count ?? '—'} pages</span></div>
        <div><span className="document-kicker">LATER VERSION</span><h2>{later.title || later.filename || 'Later document'}</h2><p>{later.filename || ''}</p><span>{later.page_count ?? '—'} pages</span></div>
      </div>
      <AnalysisTabs active="overview" onChanges={onChanges} onImpact={onImpact} onEvidence={onEvidence} />

      <section className="review-banner" data-review={data.overall_review_required ? 'true' : 'false'}>
        <strong>{data.overall_review_required ? 'Human review required' : 'No overall review flag returned'}</strong>
        <span>{data.overall_review_required ? 'Some interpretations, evidence or document limitations need manual verification.' : 'Still inspect the original policy before relying on consequential interpretations.'}</span>
      </section>

      <div className="stats-grid">
        <div className="stat-box"><strong>{counts.total ?? changes.length}</strong><span>Total findings</span></div>
        <div className="stat-box"><strong>{evidenceVerified}</strong><span>Evidence verified</span></div>
        <div className="stat-box"><strong>{needsReview}</strong><span>Needs review</span></div>
      </div>
      <div className="type-summary">
        {['added', 'removed', 'modified', 'eligibility', 'deadline', 'process', 'fee', 'document_requirement', 'clarification', 'other'].filter((type) => count(type) > 0).map((type) => (
          <div key={type}><strong>{count(type)}</strong><span>{type.replaceAll('_', ' ')}</span></div>
        ))}
      </div>

      <section className="summary-section">
        <h2>Executive summary</h2>
        <p>{data.executive_summary || 'The backend did not provide an executive summary.'}</p>
        {Array.isArray(data.key_findings) && data.key_findings.length > 0 && <><h3>Key findings</h3><ul className="finding-list">{data.key_findings.map((finding, index) => <li key={`${index}-${finding}`}>{finding}</li>)}</ul></>}
      </section>

      {limitations.length > 0 && <section className="limitations-section"><h2>Analysis limitations</h2>{limitations.map((warning, index) => <p key={`${index}-${warning}`}>⚠ {warning}</p>)}</section>}
      <p className="analysis-id-note">Analysis ID: {bundle.analysisId}</p>
      <p className="legal-note">Evidence verification confirms that a quotation was found at the cited extracted page; it does not establish legal correctness. This is assistive analysis, not legal advice.</p>
    </main>
  )
}

export default AnalysisOverview
