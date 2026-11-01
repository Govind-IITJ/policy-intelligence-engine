import { useState } from 'react'
import AnalysisTabs from './AnalysisTabs'

function ImpactActions({ bundle, onBack, onOverview, onChanges, onEvidence }) {
  const result = bundle?.result || {}
  const changes = Array.isArray(result.changes) ? result.changes : []
  const actions = Array.isArray(result.action_checklist) ? result.action_checklist : []
  const [completed, setCompleted] = useState([])

  function toggleAction(index) {
    setCompleted((previous) => previous.includes(index) ? previous.filter((item) => item !== index) : [...previous, index])
  }

  return (
    <main className="main-content impact-page">
      <button className="back-button" type="button" onClick={onBack}>← Back to workspace</button>
      <div className="eyebrow">STAKEHOLDER CONSEQUENCES</div>
      <h1>Impact &amp; Actions</h1>
      <p className="description">Potential impacts and suggested actions returned by the analysis engine. Treat these as decision-support information, not a compliance determination.</p>
      <AnalysisTabs active="impact" onOverview={onOverview} onChanges={onChanges} onEvidence={onEvidence} />

      <section>
        <h2 className="section-heading">Potential stakeholder impacts</h2>
        {changes.length === 0 ? <p className="empty-results">No change-level stakeholder information was returned.</p> : <div className="impact-list">
          {changes.map((change, index) => (
            <article className="impact-item" key={change.change_id || index}>
              <div className="impact-heading"><h3>{change.title || `Finding ${index + 1}`}</h3><span className={`change-type type-${String(change.change_type || 'other').replaceAll('_', '-')}`}>{String(change.change_type || 'other').replaceAll('_', ' ')}</span></div>
              <p>{change.explanation || 'No impact explanation was provided.'}</p>
              <div className="stakeholder-tags">{(change.affected_stakeholders || []).map((stakeholder) => <span key={stakeholder}>{stakeholder}</span>)}</div>
              {change.practical_action && <p className="impact-reference"><strong>Potential action:</strong> {change.practical_action}</p>}
              {change.review_required && <p className="inline-warning">Human review required before relying on this interpretation.</p>}
            </article>
          ))}
        </div>}
      </section>

      <section className="actions-section">
        <h2 className="section-heading">Action checklist</h2>
        <p className="actions-description">These actions come from the backend's action checklist. Checking an item is a local planning aid; it does not establish legal compliance.</p>
        {actions.length === 0 ? <p className="empty-results">No action checklist was returned for this comparison.</p> : <ul className="action-list">
          {actions.map((action, index) => (
            <li className="action-item" key={`${action.action || 'action'}-${index}`}>
              <label className="action-label"><input type="checkbox" checked={completed.includes(index)} onChange={() => toggleAction(index)} /><span>{action.action || 'Unspecified action'}</span></label>
              {action.reason && <p className="action-reason">{action.reason}</p>}
              <p className="action-reference">Source: {action.source_document || 'none'}{action.source_page != null ? ` · PDF page ${action.source_page}` : ''} · {action.source_verified === true ? 'page reference verified' : action.source_verified === false ? 'source needs review' : 'no source page supplied'}</p>
              {action.source_warning && <p className="inline-warning">{action.source_warning}</p>}
              {action.review_required && <p className="inline-warning">Human review required.</p>}
            </li>
          ))}
        </ul>}
        {actions.length > 0 && <p className="actions-progress" role="status">{completed.length} of {actions.length} actions checked in this session</p>}
      </section>
      <p className="legal-note">Stakeholder impacts may be inferred by the model and should be checked against the cited policy and applicable official instructions.</p>
    </main>
  )
}

export default ImpactActions
