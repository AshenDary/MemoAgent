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

Run the Phase 1 tests:

```bash
.venv/bin/python -m pytest tests/test_transcript_loader.py tests/test_sanitizer.py tests/test_embedder.py
```

## Status

- Phase 1 is verified locally.
- Phase 2 is in progress.
- `GET /meetings` is implemented.

## Phase 2 Finishing Work

Once the live RAG check passes, the remaining Phase 2 work is:

- Add stronger citation formatting.
- Add retrieval evaluation tests for `top_k=3` vs `top_k=10`.
- Add hallucination checks, including explicit "I don't know" behavior when evidence is weak.
- Add better logging around retrieved chunks.
- Confirm the RLS/security policy story before moving to Phase 3.

## Security Notes

- Do not hardcode secrets.
- Use the Supabase service-role key for server-side ingestion and live checks; keep the anon key for client-side reads.
- Use parameterized queries through the Supabase client.
- Sanitize all external text before storage or prompting.
- Keep transcript uploads private and workspace-scoped.

## More Context

See `../outputs/PROJECT_CONTEXT.md` for the full project context and roadmap.