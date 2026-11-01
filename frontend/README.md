# Policy Quest — Frontend v0.4.3

React + Vite user interface connected to the Policy Intelligence FastAPI backend.

## Requirements
- Node.js 20.19+ or 22.12+ (Vite 8 requirement)
- Backend running at `http://127.0.0.1:8001`

## Run

```powershell
Set-Location .rontend
npm ci
npm run build
npm.cmd run dev -- --host localhost --port 5173 --strictPort
```

Open `http://localhost:5173`. Use `localhost` (not `127.0.0.1`) for the browser origin because the backend CORS allow-list includes `http://localhost:5173`.

## Screens
- Mission Hub: executive brief, findings, review state and coverage.
- Change Arena: retained findings with earlier/later source excerpts.
- People Map: stakeholder tags connected to findings.
- Evidence Vault: source quotations, page references, verification and limitations.

## v0.4.3 report contract

The report distinguishes source quotation location, two-sided quote verification, automated clause pairing and human interpretation. Actions display their linked finding ID. A source quote being present does not establish clause equivalence or legal effect. Review warnings and partial candidate coverage remain visible.

## Build status

The production build was not verified in the packaging environment because the Vite executable was unavailable there. The final launch helper attempts `npm ci` if dependencies are absent and runs `npm run build` locally. Treat a successful local build as the required release check.
