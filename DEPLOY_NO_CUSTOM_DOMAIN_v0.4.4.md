# Secure no-custom-domain deployment (v0.4.4 patch)

This deployment keeps FastAPI and Ollama on the Windows laptop. Vercel serves the React app and a same-origin serverless proxy. Cloudflare Quick Tunnel provides a temporary HTTPS route to FastAPI. No custom domain is required.

## Security model
- Browser sends the user-entered `APP_PASSWORD` to the Vercel function over HTTPS.
- Vercel function validates it and injects `BACKEND_API_TOKEN` server-side.
- FastAPI validates `X-Backend-Token` on every `/api/*` route.
- Never put `APP_PASSWORD`, `BACKEND_API_TOKEN`, or `API_SHARED_SECRET` in any `VITE_*` variable or committed file.
- The laptop API should only bind to `127.0.0.1`; do not expose port 8001 directly.
- Do not expose Ollama port 11434.

## 1. Prepare backend
In `backend`, create `.env` from `.env.example`. Generate a secret in PowerShell:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$token = [Convert]::ToBase64String($bytes)
$token
```

Put that value in `API_SHARED_SECRET` in `backend/.env`. Keep a copy temporarily; it must also be set as Vercel `BACKEND_API_TOKEN`. Create a separate strong password for `APP_PASSWORD`.

Install/run backend (adapt the venv path if yours differs):

```powershell
Set-Location "$env:USERPROFILE\Downloads\Policy_Intelligence_Deploy\Policy_Intelligence_Engine_v0.4.3\backend"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

If this source has no adjacent venv, create one and install `requirements.txt` first. Once `API_SHARED_SECRET` is set, all `/api/*` requests require the matching token. For local Vite testing with the secret enabled, put `VITE_BACKEND_API_TOKEN=<same token>` in `frontend/.env.local` (development only); never set that variable in Vercel.

## 2. Start Quick Tunnel
In a second PowerShell window, install `cloudflared` if needed, then:

```powershell
cloudflared tunnel --url http://127.0.0.1:8001
```

Copy the generated `https://....trycloudflare.com` URL. Keep this terminal open. Quick Tunnel URLs are temporary and can change after restart.

## 3. Vercel environment variables
In Vercel Project → Settings → Environment Variables, set these for Production (and Preview only if needed):

- `BACKEND_URL` = the current `https://....trycloudflare.com` URL (no trailing slash)
- `BACKEND_API_TOKEN` = exactly the `API_SHARED_SECRET` value from backend `.env`
- `APP_PASSWORD` = a separate long password users must enter in the app

Do not create `VITE_API_BASE_URL` in Vercel. Redeploy after adding/changing variables.

## 4. Vercel project settings
Project root directory: `frontend`.
Framework: Vite. Build command: `npm run build`. Output directory: `dist`. Install command: `npm install`.
The `frontend/api/backend/[...path].js` function is deployed as a same-origin API proxy.

## 5. Test
1. Open `https://policy-intelligence-engine.vercel.app/`.
2. Trigger a document-list or upload action. Enter `APP_PASSWORD` when prompted.
3. Verify uploads, comparison creation, and analysis polling.
4. If backend reports 401, compare `API_SHARED_SECRET` and `BACKEND_API_TOKEN` exactly.
5. If backend unavailable, verify FastAPI and cloudflared terminals remain running and `BACKEND_URL` is current.

## Important limits
- Vercel Functions impose request/response size and execution limits. This proxy is intended for small demo PDFs and ordinary API responses; keep uploads below approximately 4 MB for this Vercel path.
- Long AI comparisons still execute on the laptop in FastAPI background tasks. The laptop must remain awake, connected to the internet, and running Ollama, FastAPI, and cloudflared.
- A Quick Tunnel URL is temporary. If it changes, update `BACKEND_URL` in Vercel and redeploy.
- This is a hackathon/demo architecture, not a high-availability production deployment.
