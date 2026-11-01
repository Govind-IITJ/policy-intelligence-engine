const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8001'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '')
export const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB || 20)

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.headers || {}),
      },
    })
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'Network request failed.'
    throw new Error(`Cannot reach the Policy Intelligence backend at ${API_BASE_URL}. ${reason}`)
  }

  const contentType = response.headers.get('content-type') || ''
  const body = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '')

  if (!response.ok) {
    const detail = typeof body === 'string'
      ? body
      : body?.detail || body?.message || `Request failed with HTTP ${response.status}.`
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return body
}

export async function checkBackendHealth() {
  return request('/health', { method: 'GET' })
}

export async function getAIStatus() {
  return request('/api/ai/status', { method: 'GET' })
}

export async function uploadDocument(file, version) {
  const form = new FormData()
  form.append('file', file, file.name)
  form.append('version', version)
  return request('/api/documents/upload', {
    method: 'POST',
    body: form,
  })
}

export async function startComparison(earlierDocumentId, laterDocumentId) {
  return request('/api/documents/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      earlier_document_id: earlierDocumentId,
      later_document_id: laterDocumentId,
    }),
  })
}

export async function getAnalysis(analysisId) {
  return request(`/api/analysis/${encodeURIComponent(analysisId)}`, { method: 'GET' })
}

export async function waitForAnalysis(analysisId, { onUpdate, intervalMs = 2000, timeoutMs = 15 * 60 * 1000 } = {}) {
  const startedAt = Date.now()
  let attempt = 0

  while (Date.now() - startedAt < timeoutMs) {
    const response = await getAnalysis(analysisId)
    attempt += 1
    onUpdate?.({
      status: response.status,
      attempt,
      elapsedMs: Date.now() - startedAt,
    })

    if (response.status === 'completed') {
      if (!response.result || typeof response.result !== 'object') {
        throw new Error('The backend reported completion but returned no analysis result.')
      }
      return response
    }
    if (response.status === 'failed') {
      throw new Error(response.error || 'The backend could not complete this comparison.')
    }
    if (response.status !== 'processing' && response.status !== 'queued') {
      throw new Error(`Unexpected analysis status: ${response.status || 'unknown'}`)
    }

    await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
  }

  throw new Error('Analysis timed out in the frontend. The backend job may still be running; return to the analysis ID and retry status retrieval.')
}

export function explainApiConfiguration() {
  return `Frontend API: ${API_BASE_URL}. Set VITE_API_BASE_URL in .env.local to change it.`
}
