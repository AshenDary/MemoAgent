# Meeting Memory Agent

Scaffold for an agent that ingests meeting transcripts, embeds them into pgvector, and supports semantic retrieval via API endpoints.

## Structure

- `ingestion/`: loading, cleaning, and embedding pipeline
- `retrieval/`: semantic search layer
- `agent/`: LangGraph orchestration and tools
- `api/`: FastAPI service
- `security/`: validation and PII scrubbing
- `tests/`: test suite
