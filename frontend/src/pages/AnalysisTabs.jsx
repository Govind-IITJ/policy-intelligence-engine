function AnalysisTabs({ active, onOverview, onChanges, onImpact, onEvidence }) {
  const tabs = [
    ['overview', 'Overview', onOverview],
    ['changes', 'Changes', onChanges],
    ['impact', 'Impact & Actions', onImpact],
    ['evidence', 'Evidence', onEvidence],
  ]
  return (
    <nav className="analysis-tabs" aria-label="Analysis sections">
      {tabs.map(([id, label, onClick]) => (
        <button key={id} type="button" className={`tab-button ${active === id ? 'active-tab' : ''}`} onClick={onClick} aria-current={active === id ? 'page' : undefined}>{label}</button>
      ))}
    </nav>
  )
}
export default AnalysisTabs
