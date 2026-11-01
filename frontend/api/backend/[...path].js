import { timingSafeEqual } from 'node:crypto'

export const config = { api: { bodyParser: false } }

function safeEqual(a, b) {
  const aa = Buffer.from(String(a || ''))
  const bb = Buffer.from(String(b || ''))
  return aa.length === bb.length && timingSafeEqual(aa, bb)
}

async function readBody(req) {
  const chunks = []
  for await (const chunk of req) chunks.push(Buffer.from(chunk))
  return Buffer.concat(chunks)
}

export default async function handler(req, res) {
  const appPassword = process.env.APP_PASSWORD
  const backendToken = process.env.BACKEND_API_TOKEN
  const backendUrl = (process.env.BACKEND_URL || '').replace(/\/$/, '')
  if (!appPassword || !backendToken || !backendUrl) {
    return res.status(503).json({ detail: 'Deployment environment is incomplete.' })
  }
  if (!safeEqual(req.headers['x-app-password'], appPassword)) {
    return res.status(401).json({ detail: 'Invalid access password. Reload and try again.' })
  }
  const incoming = req.url || ''
  const suffix = incoming.replace(/^\/api\/backend/, '') || '/'
  const target = `${backendUrl}${suffix}`
  const headers = { 'X-Backend-Token': backendToken, 'Accept': req.headers.accept || 'application/json' }
  if (req.headers['content-type']) headers['Content-Type'] = req.headers['content-type']
  const body = ['GET', 'HEAD'].includes(req.method) ? undefined : await readBody(req)
  try {
    const upstream = await fetch(target, { method: req.method, headers, body })
    res.status(upstream.status)
    const contentType = upstream.headers.get('content-type')
    if (contentType) res.setHeader('content-type', contentType)
    const data = Buffer.from(await upstream.arrayBuffer())
    return res.send(data)
  } catch (error) {
    return res.status(502).json({ detail: 'Laptop backend is unavailable. Check that FastAPI and Cloudflare Tunnel are running.' })
  }
}
