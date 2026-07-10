# MemoAgent Backend

This folder contains the FastAPI backend for MemoAgent. It receives transcript
uploads, cleans and chunks them, stores embeddings in Supabase pgvector, and
answers workspace-scoped meeting questions through a LangGraph agent.

## Main Features

- Upload `.txt`, `.vtt`, and `.srt` transcripts
- Validate upload type and reject files over 10MB
- Clean timestamps, speaker labels, filler words, and unsafe text
- Mask common PII before storage
- Chunk transcripts for retrieval
- Embed chunks with Gemini
- Store searchable chunks in Supabase pgvector
- Answer questions with Groq/Llama using retrieved transcript context
- Protect workspace routes with API keys

## Demo Transcripts

Use these fictional files for safe demos:

- `data/transcripts/demo/product-roadmap-review.vtt`
- `data/transcripts/demo/customer-onboarding-retrospective.srt`

They are intentionally fake and include decisions, action items, follow-ups, and
access-key discussion so the app has useful content to answer from.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:

```env
GEMINI_API_KEY=
GROQ_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_DB_URL=
SECRET_KEY=
```

Start the API:

```bash
.venv/bin/uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Basic Demo Flow

Create a key:

```bash
curl -X POST http://127.0.0.1:8000/auth/create-key \
  -H "Content-Type: application/json" \
  -d '{"workspace_id": "demo_workspace"}'
```

Upload a sample transcript:

```bash
curl -X POST http://127.0.0.1:8000/upload \
  -H "X-API-Key: YOUR_KEY_HERE" \
  -F "workspace_id=demo_workspace" \
  -F "file=@data/transcripts/demo/product-roadmap-review.vtt;type=text/vtt"
```

Ask a question:

```bash
curl -X POST http://127.0.0.1:8000/agent/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY_HERE" \
  -d '{
    "workspace_id": "demo_workspace",
    "session_id": "demo_session",
    "message": "What decisions were made in the roadmap meeting?",
    "top_k": 5
  }'
```

Useful demo questions:

- `What decisions were made?`
- `What action items came out of the meeting?`
- `What did the team say about access keys?`
- `List meetings`

## API Endpoints

- `GET /health`: process health check
- `POST /auth/create-key`: create a workspace API key
- `POST /upload`: upload and ingest a transcript
- `GET /meetings`: list stored meetings for a workspace
- `POST /query`: direct RAG question endpoint
- `POST /agent/query`: routed agent endpoint for search, summaries, decisions, and action items

## Tests

```bash
.venv/bin/python -m pytest
```

For a faster backend smoke check:

```bash
.venv/bin/python -m pytest tests/test_api_phase2.py tests/test_agent_phase2.py tests/test_sanitizer.py
```

## Deployment

Railway is the intended backend host. Set the service root to
`meeting-memory-agent/`, provide the environment variables above, and expose the
FastAPI port.

Keep `SUPABASE_SERVICE_ROLE_KEY` on the backend only. Never place it in the
frontend or in client-visible Vercel variables.

## Security Notes

- Store and compare API keys only as bcrypt hashes.
- Keep Supabase Row Level Security enabled.
- Use fictional or approved transcripts for public demos.
- Treat workspace access keys like passwords.
- Sanitize retrieved transcript content before passing it to the LLM.
