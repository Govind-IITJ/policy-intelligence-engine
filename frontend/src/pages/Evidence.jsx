import AnalysisTabs from './AnalysisTabs'

function EvidenceCard({ change, documentRole, page, quote, verified }) {
  if (page == null && !quote) return null
  const isOld = documentRole === 'Earlier version'
  return (
    <article className="evidence-item">
      <div className="evidence-topline"><span className="document-kicker">{documentRole}</span><span className={`status-pill ${verified === true ? 'verified' : verified === false ? 'warning' : 'neutral'}`}>{verified === true ? 'Verified quotation' : verified === false ? 'Not verified' : 'Not applicable / unavailable'}</span></div>
      <h3>{change.title || 'Untitled finding'}</h3>
      <p className="evidence-location">{page != null ? `PDF page ${page}` : 'Page not supplied'} · {change.change_id || change.change_type || 'Policy finding'}</p>
      <blockquote className="evidence-passage">{quote || 'No quotation was supplied for this side of the comparison.'}</blockquote>
      {isOld && change.old_evidence_verified === false && <p className="inline-warning">Earlier source quotation could not be verified against the cited extracted page.</p>}
      {!isOld && change.new_evidence_verified === false && <p className="inline-warning">Later source quotation could not be verified against the cited extracted page.</p>}
    </article>
  )
}

function Evidence({ bundle, onBack, onOverview, onChanges, onImpact }) {
  const changes = Array.isArray(bundle?.result?.changes) ? bundle.result.changes : []
  const evidenceRows = changes.flatMap((change) => [
    { key: `${change.change_id || change.title}-earlier`, change, role: 'Earlier version', page: change.old_page, quote: change.old_quote || change.old_text, verified: change.old_evidence_verified },
    { key: `${change.change_id || change.title}-later`, change, role: 'Later version', page: change.new_page, quote: change.new_quote || change.new_text, verified: change.new_evidence_verified },
  ]).filter((item) => item.page != null || item.quote)

  return (
    <main className="main-content evidence-page">
      <button type="button" className="back-button" onClick={onBack}>← Back to workspace</button>
      <div className="eyebrow">SOURCE TRACEABILITY</div>
      <h1>Evidence &amp; citations</h1>
      <p className="description">Inspect the exact passages and PDF page references attached to each returned finding.</p>
      <AnalysisTabs active="evidence" onOverview={onOverview} onChanges={onChanges} onImpact={onImpact} />
      <div className="evidence-summary"><strong>{evidenceRows.length}</strong><span>source passages supplied by the backend</span></div>
      {evidenceRows.length === 0 ? <p className="empty-results">The backend did not return source quotations for this analysis.</p> : <div className="evidence-list">
        {evidenceRows.map((item) => <EvidenceCard key={item.key} change={item.change} documentRole={item.role} page={item.page} quote={item.quote} verified={item.verified} />)}
      </div>}
      {changes.some((change) => change.evidence_warning || change.review_required) && <section className="limitations-section"><h2>Review warnings</h2>{changes.filter((change) => change.evidence_warning || change.review_required).map((change, index) => <p key={change.change_id || index}><strong>{change.title}:</strong> {change.evidence_warning || 'Human review required for this finding.'}</p>)}</section>}
      <p className="legal-note">“Verified” means the quote was matched to the extracted text on the cited page. It does not certify that the AI's interpretation or legal conclusion is correct.</p>
    </main>
  )
}

export default Evidence
