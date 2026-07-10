# MemoAgent

MemoAgent is a meeting-memory app: upload a transcript, then ask questions like
"What did we decide?", "Who owns the next step?", or "Where did we talk about
onboarding?" The answer is generated from the uploaded transcript history and
shown with source citations.

This repository contains both parts of the project:

- `meeting-memory-agent/`: FastAPI backend, transcript ingestion, retrieval, agent tools, and Supabase integration
- `frontend/`: Next.js app for workspace setup, transcript upload, chat, and citation review

## What You Can Demo

- Create a workspace access key
- Upload `.txt`, `.vtt`, or `.srt` transcript files
- Ask natural-language questions about uploaded meetings
- See citations tied back to transcript chunks
- List meetings already stored in a workspace
- Try agent-style prompts for summaries, decisions, and action items

Two safe fictional demo transcripts are included:

- `meeting-memory-agent/data/transcripts/demo/product-roadmap-review.vtt`
- `meeting-memory-agent/data/transcripts/demo/customer-onboarding-retrospective.srt`

Use these for portfolio demos instead of real private meetings.

## How The App Works

1. The backend validates the uploaded transcript file.
2. Transcript text is cleaned, sanitized, and split into chunks.
3. Chunks are embedded with Gemini and stored in Supabase pgvector.
4. When a user asks a question, the app retrieves relevant chunks for that workspace.
5. Groq/Llama generates an answer using only the retrieved context.
6. The frontend displays the answer with clickable source references.

## Local Setup

Start the backend:

```bash
cd meeting-memory-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

If port `3000` is already taken, run:

```bash
npm run dev -- -H 127.0.0.1 -p 3001
```

## Environment Variables

Create `meeting-memory-agent/.env` with:

```env
GROQ_API_KEY=
GEMINI_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_DB_URL=
SECRET_KEY=
```

For the frontend, create `frontend/.env.local` only if the backend is not on
`http://127.0.0.1:8000`:

```env
API_BASE_URL=http://127.0.0.1:8000
```

## Access Keys

The access key is a workspace-scoped API credential. It is not just a share link.
Anyone with the workspace ID and access key can upload transcripts, list meetings,
and ask questions for that workspace.

For a public portfolio deployment, use a demo workspace, fictional transcripts,
and tight rate limits. Do not use real meeting data unless the app is locked down
for authenticated users.

## Deployment Notes

Recommended portfolio setup:

- Deploy the backend from `meeting-memory-agent/` on Railway.
- Deploy the frontend from `frontend/` on Vercel.
- Set the Vercel `API_BASE_URL` environment variable to the Railway backend URL.
- Do not expose service-role Supabase credentials in the frontend.
- Consider disabling open key creation before sharing the app publicly.

## Verification

Backend tests:

```bash
cd meeting-memory-agent
.venv/bin/python -m pytest
```

Frontend build:

```bash
cd frontend
npm run build
```

## Security Notes

- Secrets are read from environment variables, never hardcoded.
- API keys are stored as bcrypt hashes.
- Uploads are limited to supported transcript formats and 10MB.
- Transcript and prompt content is sanitized before processing.
- Supabase Row Level Security should stay enabled for workspace isolation.
