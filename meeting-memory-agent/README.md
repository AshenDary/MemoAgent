# Meeting Memory Agent

Meeting Memory Agent is an Agent-as-a-Service (GaaS) project that ingests meeting transcripts, stores them in Supabase pgvector, and answers questions with grounded, cited responses.

## What It Does

- Loads `.txt`, `.vtt`, and `.srt` transcript files
- Cleans transcript noise and masks PII
- Chunks text and creates Gemini embeddings
- Stores chunk records in Supabase
- Retrieves relevant context and answers questions through a RAG flow

## Tech Stack

- Backend: FastAPI
- Agent framework: LangGraph
- LLM: Groq
- Embeddings: Gemini
- Vector DB: Supabase pgvector
- Sanitization: bleach, Pydantic, regex, optional spaCy PERSON detection
- Containerization: Docker

## Project Structure

- `ingestion/`: transcript loading, cleaning, chunking, embedding
- `retrieval/`: semantic retrieval and answer generation
- `agent/`: LangGraph tools and orchestration
- `api/`: FastAPI entrypoint
- `security/`: text sanitization and PII helpers
- `tests/`: Phase 1 and Phase 2 tests

## Setup

### Local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with the required variables:

```env
GEMINI_API_KEY=
GROQ_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_DB_URL=
SECRET_KEY=
```

### Docker

Build and run the app with the included `Dockerfile`:

```bash
docker build -t memoagent:latest -f Dockerfile .
docker run --rm --env-file .env -p 8000:8000 memoagent:latest
```

If the container expects transcript files, mount the data folder:

```bash
docker run --rm --env-file .env -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  memoagent:latest
```

## Verification

Run the test suite:

```bash
.venv/bin/python -m pytest
```

## Status

- Phase 1 is verified locally.
- Phase 2 is complete in local mocked tests: retrieval, cited RAG answers, weak-evidence fallback, retrieval logging, `top_k` evaluation coverage, and RLS schema checks are implemented.
- Phase 3 is complete for the local backend: LangGraph routes to workspace-scoped tools for transcript search, meeting summaries, decisions, action items, meeting inventory, and normal RAG answers. The API exposes `POST /agent/query` with session memory and tool-call rate limiting.
- `GET /meetings` is implemented.

## Phase 3 API

Start the API:

```bash
.venv/bin/uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Ask the Phase 3 agent:

```bash
API_KEY=$(curl -s -X POST http://127.0.0.1:8000/auth/create-key \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "workspace_123"}' | python -c "import json,sys; print(json.load(sys.stdin)['api_key'])")

curl -X POST http://127.0.0.1:8000/agent/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "workspace_id": "workspace_123",
    "session_id": "local_test",
    "message": "What action items came from the launch meeting?",
    "top_k": 5
  }'
```

Use these message styles to exercise the router:

- `"Search for launch plan mentions"` -> `search_transcripts`
- `"Summarize this meeting"` with `"meeting_id": "<filename_hash>"` -> `summarize_meeting`
- `"What decisions were made about launch?"` -> `extract_decisions`
- `"What action items are open?"` -> `find_action_items`
- `"List meetings"` -> `list_meetings`
- General questions -> `answer_from_memory`

## Next Work

Phase 4 is now in progress:

- `POST /auth/create-key` creates workspace API keys and stores only bcrypt hashes in local memory.
- `POST /query`, `POST /agent/query`, `GET /meetings`, and `POST /upload` require `X-API-Key`.
- `POST /upload` validates transcript MIME type, file extension, empty files, and the 10MB upload limit.
- CORS is deny-by-default unless `ALLOWED_ORIGINS` is set.
- Supabase schema includes RLS-enabled `api_keys` and `audit_logs` tables for the next persistence step.

Upload a transcript:

```bash
curl -X POST http://127.0.0.1:8000/upload \
  -H "X-API-Key: $API_KEY" \
  -F "workspace_id=workspace_123" \
  -F "meeting_date=2026-06-29" \
  -F "file=@/path/to/meeting.txt;type=text/plain"
```

Remaining Phase 4 hardening:

- Persist API-key hashes in Supabase instead of local process memory.
- Persist audit logs/session memory instead of keeping agent session state in process memory.

## Security Notes

- Do not hardcode secrets.
- Use the Supabase service-role key for server-side ingestion and live checks; keep the anon key for client-side reads.
- Use parameterized queries through the Supabase client.
- Sanitize all external text before storage or prompting.
- Keep transcript uploads private and workspace-scoped.

## More Context

See `../outputs/PROJECT_CONTEXT.md` for the full project context and roadmap.
