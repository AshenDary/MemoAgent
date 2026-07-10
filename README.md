# Meeting Memory Agent (MemoAgent)

**The AI employee who remembers every meeting ever held.**

`Python` `FastAPI` `LangGraph` `Next.js` `Supabase pgvector` `Groq` `Gemini`

Teams lose decisions, action items, and context between meetings. MemoAgent ingests meeting transcripts, stores them in a vector database, and lets anyone on the team ask "what did we decide about X?" in plain language — and get back a grounded answer with the exact meeting and moment it came from, not a guess.

It's built as an Agent-as-a-Service: multi-tenant, API-key scoped, with a security posture and a dark citation-first chat UI designed to actually be handed to a real team, not just run on a laptop.

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Screenshots](#screenshots)
- [Getting started](#getting-started)
- [Live Supabase and RAG checks](#live-supabase-and-rag-checks)
- [Running with Docker](#running-with-docker)
- [Frontend](#frontend)
- [Security notes](#security-notes)
- [Project status](#project-status)
- [What this project is for](#what-this-project-is-for)
- [Contributing](#contributing)

---

## Features

- **Ingests `.txt`, `.vtt`, and `.srt` transcripts** — timestamps, speaker tags, and filler words are stripped, and PII (names, emails, phone numbers) is redacted before anything touches the vector store.
- **Grounded answers, not guesses** — every claim in an agent response is traceable to a specific transcript chunk, surfaced in the UI as a clickable citation. If the evidence isn't in the transcripts, the agent says so instead of filling the gap.
- **Multi-tenant by design** — each business gets its own API key and workspace-isolated storage enforced by Supabase Row Level Security, so one team's meetings are never visible to another's.
- **An actual agent, not a fixed pipeline** — a LangGraph router decides whether to search transcripts, summarize a meeting, extract decisions, or find action items, rather than running the same retrieval step on every message.
- **Hardened API surface** — bcrypt-hashed API keys, per-workspace rate limiting, sanitized inputs, MIME/size-validated uploads, and audit-logged queries.
- **A chat UI that looks like an archive, not a demo** — dark, citation-first Next.js frontend where sources render as inline timestamped "ledger tabs" that open the exact transcript excerpt they came from.

## Architecture

**Ingestion**

```
Transcript file (.txt / .vtt / .srt)
        |
        v
  sanitize + PII scrub (bleach, spaCy)
        |
        v
  chunk (500 tokens, 50 overlap)
        |
        v
  embed (Gemini, 768-dim)
        |
        v
  Supabase pgvector, workspace-isolated via RLS
```

**Query**

```
"What did we decide about X?"
        |
        v
  embed question (Gemini)
        |
        v
  pgvector cosine similarity search (top-k)
        |
        v
  LangGraph agent: router -> tool selection -> tool execution
        |
        v
  Groq (Llama 3.3 70B) synthesis over retrieved chunks
        |
        v
  Grounded answer + citation ledger tabs (Next.js UI)
```

Every request carries a workspace-scoped API key end to end, so retrieval, tool execution, and storage all stay within that workspace's boundary.

## Tech stack

| Layer | Tool | Purpose |
|---|---|---|
| Backend | FastAPI (Python) | REST API endpoints |
| Agent framework | LangGraph | Routed, tool-calling agent logic |
| LLM | Groq (Llama 3.3 70B) | Answer synthesis |
| Embeddings | Gemini (`models/gemini-embedding-001`, 768-dim) | Text-to-vector |
| Vector DB | Supabase (pgvector) | Storage + similarity search, RLS-isolated per workspace |
| Sanitization | bleach + spaCy (optional) + regex | XSS stripping, PII redaction |
| Frontend | Next.js | Dark, citation-first chat UI |
| Containerization | Docker | Reproducible builds via the included Dockerfile |

## Screenshots

<!-- Drop a screenshot or short GIF of the chat UI here, e.g. docs/screenshot.png -->
<!-- ![MemoAgent chat UI](docs/screenshot.png) -->

## Getting started

1. Create and activate a Python virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r meeting-memory-agent/requirements.txt
   ```

2. Copy `.env.example` to `.env` and set the required environment variables:

   ```env
   GROQ_API_KEY=
   GEMINI_API_KEY=
   GEMINI_EMBEDDING_MODEL=models/gemini-embedding-001
   GEMINI_EMBEDDING_DIMENSIONS=768
   SUPABASE_URL=
   SUPABASE_KEY=
   SUPABASE_DB_URL=
   SECRET_KEY=
   ```

3. Place transcript files under `meeting-memory-agent/data/transcripts/raw/` (this folder is git-ignored).

4. Run the Phase 1 unit tests to verify ingestion and sanitizer behavior:

   ```bash
   .venv/bin/python -m pytest meeting-memory-agent/tests/test_transcript_loader.py \
       meeting-memory-agent/tests/test_sanitizer.py \
       meeting-memory-agent/tests/test_embedder.py
   ```

## Live Supabase and RAG checks

Run these from `meeting-memory-agent/` after `.env` is configured.

```bash
# Apply schema through a direct Postgres connection.
.venv/bin/python scripts/apply_supabase_schema.py

# Confirm the app can read the transcript_chunks table.
.venv/bin/python scripts/test_supabase_connection.py

# Ingest a synthetic transcript, query it with Gemini + Supabase + Groq, then clean up test rows.
.venv/bin/python scripts/run_live_rag_check.py
```

If direct Postgres DNS does not resolve locally, paste `supabase/schema.sql` into the Supabase SQL Editor, run it there, then rerun the two check scripts. `SUPABASE_URL` should be the project base URL only, with no `/rest/v1` path.

## Running with Docker

You can build and run the project in a container using the included `meeting-memory-agent/Dockerfile`.

```bash
# Build the Docker image from the repo root
docker build -f meeting-memory-agent/Dockerfile -t memoagent:latest .

# Run the container, passing environment variables from .env and exposing port 8000
docker run --rm --env-file .env -p 8000:8000 \
  -v $(pwd)/meeting-memory-agent/data:/app/meeting-memory-agent/data \
  memoagent:latest
```

Notes:
- Ensure Docker is installed and running locally.
- The container uses the same env vars as the local setup; provide them via `--env-file .env` or `-e` flags.
- If the container's entrypoint uses a different port, change the `-p` mapping accordingly.

## Frontend

Run the Phase 5 UI from `frontend/`:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Set `API_BASE_URL` in `.env.local` only if the FastAPI backend is not running at `http://127.0.0.1:8000`. Vercel/Railway deployment notes live in `frontend/README.md`.

## Security notes

- No secrets are committed. Runtime keys load from `.env` via `python-dotenv`.
- All inputs are sanitized with `bleach` and validated with Pydantic.
- Database access goes through the Supabase Python client with parameterized queries — no f-string SQL.
- PII redaction uses regex for emails/phones and spaCy for person names, with a safe fallback if spaCy isn't installed.

## Project status

- [x] **Phase 1 — Ingestion + Sanitization**: transcript loading, sanitization, PII masking, chunking, embedding record prep, Supabase persistence helpers, tests passing.
- [x] **Phase 2 — RAG Core**: tenant-scoped pgvector retrieval, Groq answer generation with citation prompting, a LangGraph RAG entry point, the `/query` endpoint, a live RAG check script, and tests.
- [x] **Phase 3 — Agent layer**: routed tool execution, session memory, audit logging.
- [x] **Phase 4 — API + security hardening**: API-key auth, request-level rate limiting, Supabase-backed stores, XSS sanitization, upload validation, revoked-key handling, workspace-scoped persistence.
- [x] **Phase 5 — Frontend + deployment**: dark research-ledger app shell, workspace API-key setup, transcript upload, meeting inventory, memory query flow, clickable citation ledger tabs, responsive mobile sheets, Vercel/Railway deployment notes.

All five build phases are implemented locally. Open items are tracked as GitHub issues rather than in this README.

## What this project is for

This started as a way to learn RAG, agentic workflows, and applied security by building something real rather than following a tutorial — every phase deliberately paired a feature with a security concept (parameterized queries, Row Level Security, rate limiting, hashed keys, prompt injection defense) instead of bolting security on at the end. It's also meant to work as an actual product: a business could hand this to their team today and get value from it, not just a proof of concept.

## Contributing

Contributions are welcome. Open an issue for feature requests or security concerns. If you're adding a feature that requires system packages (e.g. spaCy model downloads), document the installation steps in this README.
