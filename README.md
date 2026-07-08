# Meeting Memory Agent (MemoAgent)

Meeting Memory Agent is an Agent-as-a-Service (GaaS) that acts like an AI employee for teams: it ingests meeting transcripts, stores them in a vector database (pgvector), and lets members query their meeting history using natural language to get grounded answers with citations.

## Key Features

- Ingestion pipeline for `.txt`, `.vtt`, and `.srt` transcripts
- Sanitization and PII redaction (emails, phones, names)
- Chunking (500 token chunks, 50 token overlap) and embedding via Gemini
- Storage in Supabase `pgvector` with deduplication support
- Unit tests for ingestion and sanitizer utilities

## Tech Stack

- Backend: FastAPI (Python)
- Agent framework: LangGraph
- LLM: Groq (Llama 3.3 70B)
- Embeddings: Google Gemini (`models/gemini-embedding-001`, 768 dimensions by default)
- Vector DB: Supabase (pgvector)
- Sanitization: bleach + spaCy (optional) + regex

## Getting started

1. Create and activate a Python virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r meeting-memory-agent/requirements.txt
```

2. Copy `.env.example` to `.env` and set the required environment variables:

```
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

## Project status

- Phase 1 (Ingestion + Sanitization) — verified locally. Transcript loading, sanitization, PII masking, chunking, embedding record preparation, Supabase persistence helpers, and Phase 1 tests are passing.
- Phase 2 (RAG Core) — complete in local mocked tests. The repo has tenant-scoped pgvector retrieval, Groq answer generation with citation prompting, a LangGraph RAG entry point, a `/query` API endpoint, a live RAG check script, and tests around the RAG path.
- Phase 3 (Agent layer) — complete in the local backend. The LangGraph flow includes routed tool execution, session memory, and audit logging.
- Phase 4 (API + security hardening) — complete locally and covered by tests. API-key auth, request-level rate limiting, Supabase-backed stores, XSS sanitization, upload validation, revoked-key handling, and workspace-scoped persistence are implemented.
- Phase 5 (Frontend + deployment) — implemented locally. The Next.js client now has the dark research-ledger app shell, workspace API-key setup, transcript upload, meeting inventory, one user-friendly memory query flow, clickable citation ledger tabs, responsive mobile sheets, and Vercel/Railway deployment notes in `frontend/README.md`.

## Frontend

Run the Phase 5 UI from `frontend/`:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Set `API_BASE_URL` in `.env.local` only if the FastAPI backend is not running at `http://127.0.0.1:8000`.

## Security notes

- Do not commit secrets. Use `.env` and `python-dotenv` for runtime keys.
- Sanitize all inputs with `bleach` and validate with Pydantic.
- Use the Supabase Python client for parameterized queries; avoid f-string SQL.
- PII redaction uses regex for emails/phones and spaCy for person names (spaCy is optional and has a safe fallback).

## Contributing

Contributions welcome. Open issues for feature requests or security concerns. If adding features that require system packages (e.g., spaCy model downloads), document installation steps in this README.

If you'd like a minimal ingestion CLI or an `/upload` endpoint to exercise Phase 1 end-to-end, tell me and I will add it next.

---

For full project context and architecture details, see `outputs/PROJECT_CONTEXT.md`.
