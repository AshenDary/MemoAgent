# Meeting Memory Agent

Scaffold for an agent that ingests meeting transcripts, embeds them into pgvector, and supports semantic retrieval via API endpoints.

## Structure

- `ingestion/`: loading, cleaning, and embedding pipeline
- `retrieval/`: semantic search layer
- `agent/`: LangGraph orchestration and tools
- `api/`: FastAPI service
- `security/`: validation and PII scrubbing
- `tests/`: test suite

## Local transcript files

Put real meeting transcripts in `data/transcripts/raw/`.

That folder is git-ignored except for `.gitkeep`, because raw meeting transcripts can contain private names, emails, decisions, and business context.

Supported Phase 1 formats:

- `.txt`
- `.vtt`
- `.srt`
