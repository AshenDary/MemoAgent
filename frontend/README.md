# MemoAgent Frontend

This directory contains the Phase 5 Next.js client for MemoAgent: a dark research-ledger workspace for transcript upload, meeting memory questions, meeting inventory, and citation review.

## What it does

- Provides a simple conversation surface backed by `POST /agent/query`
- Supports transcript uploads into `POST /upload`
- Lists workspace meetings from `GET /meetings`
- Renders citations as clickable ledger tabs that open the source drawer
- Includes workspace API-key creation for local setup through `POST /auth/create-key`
- Proxies backend calls through `/api/backend` so browser requests avoid local CORS issues

## Local setup

1. Install dependencies:

```bash
cd frontend
npm install
```

2. Copy the environment example:

```bash
cp .env.example .env.local
```

3. Run the app:

```bash
npm run dev
```

4. Open the local app:

```text
http://127.0.0.1:3000
```

## Backend setup

Run the FastAPI app separately from `meeting-memory-agent/`:

```bash
.venv/bin/uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

By default, the frontend proxy forwards requests to `http://127.0.0.1:8000`.
Set `API_BASE_URL` or `NEXT_PUBLIC_API_BASE_URL` in `.env.local` only if your backend runs somewhere else:

```env
API_BASE_URL=http://127.0.0.1:8000
```

## Deployment

- Vercel: set the project root to `frontend/`, set `API_BASE_URL` to the Railway backend URL, and deploy with the default Next.js settings.
- Railway: deploy the FastAPI service from `meeting-memory-agent/` and provide the required API keys and Supabase variables.

## Notes

- The UI expects the FastAPI backend to be running separately.
- API requests use `X-API-Key` and the workspace ID supplied in the form.
- API keys are held in client state only; do not paste production service-role credentials into the browser.
