# Frontend integration status

## Implemented

- Real FastAPI health check at `GET /health`.
- Earlier and later PDF upload via `POST /api/documents/upload` (`file` and `version` multipart fields).
- Comparison creation via `POST /api/documents/compare`.
- Analysis polling via `GET /api/analysis/{analysis_id}` until `completed` or `failed`.
- Real response rendering in Overview, Changes, Impact & Actions and Evidence screens.
- Visible evidence-verification and human-review states.
- Configurable `VITE_API_BASE_URL` and upload size limit.
- Vite pinned to `http://localhost:5173` to match the backend's default CORS allow-list.
- PowerShell launcher that checks the backend, installs dependencies if missing, and starts Vite.

## Not verified in this build environment

The source changes are present, but a production build and browser end-to-end test could not be run here because the npm registry was unreachable (`EAI_AGAIN`) while installing dependencies. Run `START_FRONTEND.ps1` on the Windows development machine; it will run `npm ci` using the included lockfile, then launch Vite.

## Run locally

1. Start the FastAPI backend on port 8001.
2. Run `START_FRONTEND.ps1` from this folder.
3. Open `http://localhost:5173`.
4. Upload an earlier and later policy PDF and start analysis.

If the browser reports a CORS error, ensure the backend `.env` includes `CORS_ORIGINS=http://localhost:5173,http://localhost:3000` and restart FastAPI.
