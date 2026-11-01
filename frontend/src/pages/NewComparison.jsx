import { useRef, useState } from 'react'
import { MAX_UPLOAD_MB, checkBackendHealth, uploadDocument, startComparison, waitForAnalysis } from '../services/api'

const MAX_SIZE = MAX_UPLOAD_MB * 1024 * 1024

async function looksLikePdf(file) {
  if (!file.name.toLowerCase().endsWith('.pdf')) return false
  const head = await file.slice(0, 1024).text()
  return head.includes('%PDF-')
}

function UploadArea({ title, version, file, onFileChange, disabled }) {
  const inputRef = useRef(null)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)

  async function handleFile(selectedFile) {
    if (!selectedFile) return
    if (selectedFile.size > MAX_SIZE) {
      setError(`PDF must be ${MAX_UPLOAD_MB} MB or smaller.`)
      return
    }
    const validPdf = await looksLikePdf(selectedFile).catch(() => false)
    if (!validPdf) {
      setError('The selected file does not appear to be a valid PDF. Please choose the original PDF document.')
      return
    }
    setError('')
    onFileChange(selectedFile)
  }

  return (
    <div className="upload-area">
      <div className="upload-label-row">
        <h2><span className="upload-step-icon">{version === 'earlier' ? '01' : '02'}</span>{title}</h2>
        <span className="version-chip">{version === 'earlier' ? 'Version 1' : 'Version 2'}</span>
      </div>
      <div
        className={`upload-box ${file ? 'has-file' : '' } ${dragging ? 'drag-active' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); if (!disabled) setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false) }}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          if (!disabled) void handleFile(event.dataTransfer.files[0])
        }}
      >
        <span className="upload-icon" aria-hidden="true">{file ? '✓' : dragging ? '✦' : '↥'}</span>
        {file ? (
          <>
            <p className="file-name">{file.name}</p>
            <p className="file-details">{(file.size / (1024 * 1024)).toFixed(2)} MB · PDF selected</p>
            <div className="file-actions">
              <button className="secondary-button" type="button" disabled={disabled} onClick={() => inputRef.current?.click()}>Replace</button>
              <button className="remove-button" type="button" disabled={disabled} onClick={() => { onFileChange(null); setError(''); if (inputRef.current) inputRef.current.value = '' }}>Remove</button>
            </div>
          </>
        ) : (
          <>
            <p>{dragging ? 'Release to add your PDF' : `Drop the ${version} PDF here`}</p>
            <p className="file-details">PDF · Up to {MAX_UPLOAD_MB} MB</p>
            <button className="secondary-button" type="button" disabled={disabled} onClick={() => inputRef.current?.click()}>Browse files</button>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="visually-hidden"
          aria-label={`Choose ${title} PDF`}
          disabled={disabled}
          onChange={(event) => { void handleFile(event.target.files[0]); event.target.value = '' }}
        />
      </div>
      {error && <p className="upload-error" role="alert">{error}</p>}
    </div>
  )
}

function NewComparison({ onBack, onComplete }) {
  const [earlier, setEarlier] = useState(null)
  const [later, setLater] = useState(null)
  const [phase, setPhase] = useState('idle')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [details, setDetails] = useState('')
  const busy = phase !== 'idle' && phase !== 'failed'

  async function handleAnalyse(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    setDetails('')
    if (!earlier || !later) return

    try {
      setPhase('checking')
      setMessage('Checking backend connection…')
      await checkBackendHealth()

      setPhase('uploading-earlier')
      setMessage('Uploading earlier version…')
      const earlierDoc = await uploadDocument(earlier, 'earlier')
      setDetails(`${earlierDoc.page_count} pages extracted · ${earlierDoc.extracted_characters.toLocaleString()} characters`)

      setPhase('uploading-later')
      setMessage('Uploading later version…')
      const laterDoc = await uploadDocument(later, 'later')
      setDetails(`Earlier: ${earlierDoc.page_count} pages · Later: ${laterDoc.page_count} pages`)

      setPhase('starting')
      setMessage('Starting policy comparison…')
      const started = await startComparison(earlierDoc.document_id, laterDoc.document_id)

      setPhase('processing')
      setMessage('The analysis engine is comparing both versions. This can take several minutes for large PDFs.')
      setDetails(`Analysis ID: ${started.analysis_id}`)
      const completed = await waitForAnalysis(started.analysis_id, {
        onUpdate: ({ attempt, elapsedMs }) => setDetails(`Analysis ID: ${started.analysis_id} · Status checks: ${attempt} · Elapsed: ${Math.max(1, Math.round(elapsedMs / 1000))}s`),
      })

      setPhase('completed')
      setMessage('Comparison completed. Opening the actual backend findings…')
      onComplete({
        analysisId: started.analysis_id,
        result: completed.result,
        earlierDocument: earlierDoc,
        laterDocument: laterDoc,
        completedAt: completed.updated_at,
      })
    } catch (requestError) {
      setPhase('failed')
      setError(requestError instanceof Error ? requestError.message : 'Comparison failed. Please retry.')
      setMessage('The comparison did not complete.')
    }
  }

  return (
    <main className="main-content comparison-content">
      <button className="back-button" onClick={onBack} type="button" disabled={busy}>← Back to workspace</button>
      <div className="comparison-quest-head">
        <div className="eyebrow"><span className="eyebrow-spark">✦</span> NEW MISSION · LOAD YOUR FILES</div>
        <div className="quest-step-chip">STEP 01 <span>OF 03</span></div>
      </div>
      <h1>Drop your policy cards.</h1>
      <p className="description">Add the earlier and later versions. We’ll scan the differences and build an interactive trail through the findings.</p>
      <div className="upload-route"><span className={earlier ? 'complete' : 'active'}>01 <b>Earlier version</b></span><i/><span className={later ? 'complete' : ''}>02 <b>Later version</b></span><i/><span className={phase === 'processing' || phase === 'completed' ? 'active' : ''}>03 <b>Scan & explore</b></span></div>

      <form onSubmit={handleAnalyse}>
        <div className="upload-grid">
          <UploadArea title="Earlier version" version="earlier" file={earlier} onFileChange={setEarlier} disabled={busy} />
          <UploadArea title="Later version" version="later" file={later} onFileChange={setLater} disabled={busy} />
        </div>
        <div className="form-actions">
          <button className="primary-button launch-button" type="submit" disabled={!earlier || !later || busy}>
            {busy ? 'Scanning your policy cards…' : 'Launch policy scan'} <span>↗</span>
          </button>
        </div>
      </form>

      {message && (
        <section className={`progress-panel ${phase}`} role="status" aria-live="polite">
          <span className={`progress-spinner ${phase === 'completed' ? 'done' : ''}`} aria-hidden="true">{phase === 'completed' ? '✓' : '↻'}</span>
          <div><strong>{message}</strong>{details && <p>{details}</p>}</div>
        </section>
      )}
      {error && <div className="error-panel" role="alert"><strong>Could not complete comparison</strong><p>{error}</p><small>Uploaded documents, if any, remain stored by the backend. Retry by selecting the same versions again.</small></div>}
      <p className="legal-note">Use two versions of the same policy. Automated findings are decision-support outputs and may require human review.</p>
    </main>
  )
}

export default NewComparison
