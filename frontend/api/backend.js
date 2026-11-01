import { timingSafeEqual } from 'node:crypto'

function safeEqual(a, b) {
  const aa = Buffer.from(String(a || ''))
  const bb = Buffer.from(String(b || ''))
  return aa.length === bb.length && timingSafeEqual(aa, bb)
}

function json(status, detail) {
  return Response.json({ detail }, { status })
}

export default {
  async fetch(request) {
    const appPassword = process.env.APP_PASSWORD
    const backendToken = process.env.BACKEND_API_TOKEN
    const backendUrl = (process.env.BACKEND_URL || '').replace(/\/$/, '')

    if (!appPassword || !backendToken || !backendUrl) {
      return json(503, 'Deployment environment is incomplete.')
    }

    if (!safeEqual(request.headers.get('x-app-password'), appPassword)) {
      return json(401, 'Invalid access password. Reload and try again.')
    }

    const incoming = new URL(request.url)
    const route = incoming.searchParams.get('__route') || ''
    const segments = route.split('/').filter(Boolean)

    if (segments.some((part) => part === '.' || part === '..' || part.includes('\\'))) {
      return json(400, 'Invalid backend route.')
    }

    const backendPath = '/' + segments.map((part) => encodeURIComponent(part)).join('/')
    const target = new URL(backendPath, `${backendUrl}/`)
    for (const [key, value] of incoming.searchParams.entries()) {
      if (key !== '__route') target.searchParams.append(key, value)
    }

    const headers = new Headers({
      'X-Backend-Token': backendToken,
      'Accept': request.headers.get('accept') || 'application/json',
    })
    const contentType = request.headers.get('content-type')
    if (contentType) headers.set('Content-Type', contentType)

    try {
      const method = request.method.toUpperCase()
      const body = method === 'GET' || method === 'HEAD' ? undefined : await request.arrayBuffer()
      const upstream = await fetch(target, { method, headers, body, redirect: 'manual' })
      const responseHeaders = new Headers()
      for (const name of ['content-type', 'content-disposition', 'cache-control', 'retry-after']) {
        const value = upstream.headers.get(name)
        if (value) responseHeaders.set(name, value)
      }
      return new Response(upstream.body, {
        status: upstream.status,
        headers: responseHeaders,
      })
    } catch {
      return json(502, 'Laptop backend is unavailable. Check that FastAPI and Cloudflare Tunnel are running.')
    }
  },
}
