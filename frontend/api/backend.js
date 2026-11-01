function json(status, detail) {
  return Response.json({ detail }, { status })
}

function isAllowedRoute(method, path) {
  if (method === 'GET' && (path === '/health' || path === '/api/ai/status' || path === '/api/documents')) return true
  if (method === 'POST' && (path === '/api/documents/upload' || path === '/api/documents/compare')) return true
  if (method === 'GET' && /^\/api\/documents\/[A-Za-z0-9_-]{1,128}$/.test(path)) return true
  if (method === 'GET' && /^\/api\/documents\/[A-Za-z0-9_-]{1,128}\/pages\/[1-9][0-9]{0,4}$/.test(path)) return true
  if (method === 'GET' && /^\/api\/analysis\/[A-Za-z0-9_-]{1,128}(?:\/changes)?$/.test(path)) return true
  return false
}

export default {
  async fetch(request) {
    const backendToken = process.env.BACKEND_API_TOKEN
    const backendUrl = (process.env.BACKEND_URL || '').replace(/\/$/, '')

    // APP_PASSWORD is deliberately not required in Public Judge Mode.
    // The private backend token is injected here and never sent to the browser.
    if (!backendToken || !backendUrl) {
      return json(503, 'Deployment environment is incomplete. Configure BACKEND_URL and BACKEND_API_TOKEN.')
    }

    const incoming = new URL(request.url)
    const route = incoming.searchParams.get('__route') || ''
    const segments = route.split('/').filter(Boolean)

    if (!segments.length || segments.some((part) => part === '.' || part === '..' || part.includes('\\'))) {
      return json(400, 'Invalid backend route.')
    }

    const method = request.method.toUpperCase()
    const backendPath = '/' + segments.join('/')
    if (!isAllowedRoute(method, backendPath)) {
      return json(404, 'This API route is not available in Public Judge Mode.')
    }

    const target = new URL('/' + segments.map((part) => encodeURIComponent(part)).join('/'), `${backendUrl}/`)
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
      const body = method === 'GET' || method === 'HEAD' ? undefined : await request.arrayBuffer()
      const upstream = await fetch(target, { method, headers, body, redirect: 'manual' })
      const responseHeaders = new Headers()
      for (const name of ['content-type', 'content-disposition', 'cache-control', 'retry-after']) {
        const value = upstream.headers.get(name)
        if (value) responseHeaders.set(name, value)
      }
      responseHeaders.set('Cache-Control', 'no-store')
      return new Response(upstream.body, { status: upstream.status, headers: responseHeaders })
    } catch {
      return json(502, 'Laptop backend is unavailable. Check that FastAPI and Cloudflare Tunnel are running.')
    }
  },
}
