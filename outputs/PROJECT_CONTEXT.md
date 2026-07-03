# Meeting Memory Agent - Project Context

## What This Project Is
An **Agent-as-a-Service (GaaS)** product that acts as an AI employee for businesses.
It ingests meeting transcripts, stores them in a vector database, and lets team members
query their entire meeting history using natural language, getting grounded, cited answers.

**Tagline:** "The AI employee who remembers every meeting ever held."

---

## Business Use Case
- Target: SMEs and teams who lose decisions, action items, and context between meetings
- Delivered as: a web service with an API key per business (multi-tenant)
- Value: ask "what did we decide about X?" and get an answer with the exact meeting source cited

---

## Tech Stack (all free tier)

| Layer | Tool | Purpose |
|---|---|---|
| LLM | Groq API (Llama 3.3 70B) | Answer generation |
| Embeddings | Gemini API (`models/gemini-embedding-001`, 768 dimensions by default) | Convert text to vectors |
| Vector DB | Supabase pgvector | Store + search embeddings |
| Agent framework | LangGraph | Agentic tool-calling logic |
| Backend | FastAPI (Python) | REST API endpoints |
| Frontend | Next.js | Chat UI |
| Hosting | Railway (backend) + Vercel (frontend) | Free deployment |
| Containerization | Docker | Build and run using the included Dockerfile |
| PII detection | spaCy (en_core_web_sm) | Detect names, emails in transcripts |
| Sanitization | bleach + pydantic | Strip XSS, validate inputs |
| Scheduling | APScheduler | Optional: auto-ingest |

---

## Project Folder Structure

```text
meeting-memory-agent/
|-- ingestion/
|   |-- transcript_loader.py     # load .txt, .vtt, .srt files
|   |-- sanitizer.py             # clean + PII scrub transcript data
|   `-- embedder.py              # chunk text + embed + store in pgvector
|-- retrieval/
|   `-- retriever.py             # cosine similarity search from pgvector
|-- agent/
|   |-- graph.py                 # LangGraph agent definition
|   `-- tools.py                 # tools the agent can call
|-- api/
|   `-- main.py                  # FastAPI: POST /auth/create-key, /upload, /query, /agent/query, /meetings
|-- security/
|   |-- auth.py                  # hashed API keys and verification helpers
|   |-- stores.py                # API key, session, and audit-log persistence
|   `-- sanitize.py              # input validation, injection prevention
|-- tests/
|   `-- test_sanitizer.py        # security tests
|-- .env                         # secrets - NEVER commit
|-- .gitignore                   # .env must be listed here
|-- requirements.txt
`-- README.md
```

---

## Data Flow

### Ingestion pipeline
```text
Raw transcript file
  -> transcript_loader.py  (read file, detect format)
  -> sanitizer.py          (strip timestamps, speaker tags, PII masking)
  -> chunker               (500 token chunks, 50 token overlap)
  -> embedder.py           (Gemini API -> vector)
  -> Supabase pgvector     (store chunk + vector + metadata)
```

### Query pipeline
```text
User question
  -> embed question (Gemini API)
  -> pgvector cosine similarity search (top-k chunks)
  -> LangGraph agent (decides which tools to call)
  -> Groq LLM (Llama 3.3 70B) with retrieved context
  -> grounded answer with citations (meeting date + source)
```

---

## Build Phases

### Phase 1 - Week 1: Ingestion + Sanitation
**Goal:** Load transcripts, clean them, embed them, store in pgvector

Tasks:
- transcript_loader.py: handle .txt, .vtt (Zoom), .srt formats
- sanitizer.py: strip timestamps [00:01:23], speaker labels "John:", filler words
- PII scrubbing: mask emails, phone numbers, names using spaCy NER
- Chunker: LangChain RecursiveCharacterTextSplitter (500 tokens, 50 overlap)
- Embedder: call configured Gemini embedding model, store 768-dimensional vectors in Supabase
- Deduplication: hash transcript URL/filename before storing; skip if exists
- Input validation: reject files > 10MB, non-text formats, sanitize content

Security learned: SQL injection prevention, parameterized queries, PII masking, .env secrets

### Phase 2 - Week 2: RAG Core
**Goal:** Build the retrieval + generation chain

Tasks:
- retriever.py: embed query -> pgvector similarity search -> return top-k chunks
- RAG chain: retrieved chunks + question -> Groq LLM -> answer with citations
- Prompt engineering: instruct LLM to cite meeting date and source inline
- Evaluation: test k=3 vs k=10, test hallucination vs grounded answers
- Supabase RLS: Row Level Security; users only access their own transcripts

Security learned: Row Level Security, data isolation, grounded vs hallucinated outputs

### Phase 3 - Week 3: Agentic Layer
**Goal:** LangGraph agent that decides what to do, not just retrieve

Agent tools:
- search_transcripts(query): semantic search
- summarize_meeting(meeting_id): summarize a specific meeting
- extract_decisions(query): pull out decisions made
- find_action_items(query): find tasks assigned to people
- list_meetings(date_range): list available meetings

LangGraph flow: User message -> Router node -> Tool selection -> Tool execution -> LLM synthesis -> Response

Additional:
- Multi-turn memory: agent tracks conversation context
- Rate limiting: max 20 tool calls per session
- Audit logging: log every query + what was retrieved (Loguru)
- Prompt injection defense: sanitize retrieved content before passing to LLM

Security learned: Agent boundaries, rate limiting, audit logging, prompt injection

### Phase 4 - Week 4: API + Security Hardening
**Goal:** FastAPI backend, properly secured

Endpoints:
- POST /upload: upload transcript file
- POST /query: ask a question, get answer + citations
- GET /meetings: list uploaded meetings
- POST /auth/create-key: create API key for a workspace

Security implementation:
- API key auth: keys hashed with bcrypt before storage, never stored plaintext
- Input sanitization: bleach.clean() on all text inputs, pydantic validation
- File upload: validate MIME type, limit to 10MB, scan for malicious content
- CORS: whitelist only your frontend domain
- HTTPS: enforced at Railway deployment level
- Security tests: attempt SQL injection, XSS payloads, oversized files against your own API

Security learned: Hashed API keys, CORS, XSS prevention, penetration testing your own API

### Phase 5 - Week 5: Frontend + GaaS Deployment
**Goal:** Ship it as a real multi-tenant business service

Tasks:
- Next.js chat UI: file upload, streaming chat, citations shown inline
- Multi-tenant: each business = isolated workspace + scoped API key
- Deploy: Railway (FastAPI) + Vercel (Next.js)
- README with architecture diagram (portfolio artifact)

GaaS architecture: each tenant has isolated vector namespace in Supabase, scoped API keys

---

## Security Checklist (per phase)

| Phase | Security Focus |
|---|---|
| Phase 1 | .env secrets, parameterized queries, PII masking, input validation |
| Phase 2 | Supabase RLS, no raw SQL strings, sanitize before embed |
| Phase 3 | Rate limiting, audit logs, tool call boundaries, prompt injection defense |
| Phase 4 | Hashed API keys, CORS, HTTPS, XSS strip, file size limits |
| Phase 5 | Multi-tenant isolation, workspace-scoped data, no cross-tenant leakage |

---

## Key Security Rules (always follow)

1. **Never hardcode secrets**: always os.getenv() via python-dotenv
2. **Parameterized queries only**: use Supabase Python client, never f-string SQL
3. **Validate all external input**: scraped/uploaded content is untrusted
4. **Hash API keys**: bcrypt before storing, compare hash not plaintext
5. **Sanitize before LLM**: strip injected instructions from retrieved content
6. **Use service-role keys server-side**: keep anon keys for client reads and service-role keys for ingestion and maintenance scripts under RLS.

---

## Environment Variables Required

```env
GROQ_API_KEY=
GEMINI_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SECRET_KEY=          # for signing tokens
```

## Docker

- A Dockerfile is included in the repository (meeting-memory-agent/Dockerfile) so you can run the service in a container.
- Example: build and run the image locally (assumes Docker is installed):

```bash
# Build the image from the project root
docker build -f meeting-memory-agent/Dockerfile -t memoagent:latest .

# Run with environment file, expose port 8000, and mount local data folder
docker run --rm --env-file .env -p 8000:8000 \
  -v $(pwd)/meeting-memory-agent/data:/app/meeting-memory-agent/data \
  memoagent:latest
```

Notes:
- The container expects the same environment variables as the local setup. Use `--env-file .env` or `-e` flags to pass them.
- Adjust the `-p` port mapping if your FastAPI process is configured for a different port.

---

## Current Status
Phase 1 verified locally. Transcript loading, sanitization, PII masking,
chunking, embedding record preparation, Supabase persistence helpers, and
Phase 1 tests are implemented and passing.

Phase 2 is complete in local mocked tests. The RAG core includes query embedding,
tenant-scoped Supabase pgvector retrieval, retrieved-content sanitization, Groq
answer generation with source-style citation labels, weak-evidence "I do not
know" fallback behavior, retrieval audit logging, and tests for `top_k=3` vs
`top_k=10`. The API has a Phase 2 `POST /query` endpoint plus `GET /meetings`,
and the Supabase schema enables RLS without adding broad anon policies.

Phase 3 is complete for the local backend. LangGraph now uses a routed agent flow:

```text
User message -> deterministic router -> bounded tool execution -> response synthesis
```

Implemented tools:
- `search_transcripts(query)`
- `summarize_meeting(meeting_id)`
- `extract_decisions(query)`
- `find_action_items(query)`
- `list_meetings(date_range)`
- `answer_from_memory(question)`

Phase 3 guardrails implemented:
- Max 20 tool calls per session
- Short conversation history in graph state
- Loguru audit logs for tool calls
- Retrieved content sanitization before prompting or extraction
- `POST /agent/query` API endpoint with persisted per-session state through the security store layer

## Phase 4 Current Status

Phase 4 is now partially implemented in the backend and mostly in place locally:
- `POST /auth/create-key` creates workspace API keys and stores only bcrypt hashes.
- `POST /query`, `POST /agent/query`, `GET /meetings`, and `POST /upload` all require `X-API-Key`.
- `POST /upload` validates transcript MIME type, extension, empty files, and the 10MB upload limit before ingestion.
- `security/stores.py` now provides pluggable persistence for API keys, agent session state, and audit logs, with Supabase-backed implementations and an in-memory fallback for local runs.
- `api/main.py` wires the stores into request handling so agent session state and audit events are saved after requests.
- The Supabase schema includes RLS-enabled `api_keys`, `agent_sessions`, and `audit_logs` tables.
- Tests cover auth creation, missing keys, cross-workspace rejection, upload validation, oversized files, and agent-session persistence behavior.

Remaining Phase 4 hardening:
- Verify Supabase-backed stores end-to-end with live credentials instead of only local fallback and mocked tests.
- Add broader security tests for XSS and auth edge cases.
- Add any missing RLS policies once multi-tenant workspace membership is finalized.

## Learning Goals
- Understand and implement RAG from scratch, not just use a library
- Build real LangGraph agentic workflows with tool-calling
- Learn security practices: SQL injection, XSS, PII, API key security
- Ship a GaaS product that could serve real businesses
- Build a CV-worthy AI Engineering project
