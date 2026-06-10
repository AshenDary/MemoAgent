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
| Embeddings | Gemini API (text-embedding-004) | Convert text to vectors |
| Vector DB | Supabase pgvector | Store + search embeddings |
| Agent framework | LangGraph | Agentic tool-calling logic |
| Backend | FastAPI (Python) | REST API endpoints |
| Frontend | Next.js | Chat UI |
| Hosting | Railway (backend) + Vercel (frontend) | Free deployment |
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
|   `-- main.py                  # FastAPI: POST /upload, POST /query, GET /meetings
|-- security/
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
- Embedder: call Gemini text-embedding-004, store result in Supabase
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

---

## Environment Variables Required

```env
GROQ_API_KEY=
GEMINI_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
SECRET_KEY=          # for signing tokens
```

---

## Current Status
Starting Phase 1. Setting up project structure, installing dependencies,
creating .env file, getting API keys from Groq + Gemini + Supabase.

## Learning Goals
- Understand and implement RAG from scratch, not just use a library
- Build real LangGraph agentic workflows with tool-calling
- Learn security practices: SQL injection, XSS, PII, API key security
- Ship a GaaS product that could serve real businesses
- Build a CV-worthy AI Engineering project
