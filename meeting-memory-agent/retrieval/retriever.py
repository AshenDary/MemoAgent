"""Phase 2 RAG retrieval and answer generation."""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Any, Optional

from dotenv import load_dotenv
from groq import Groq
from loguru import logger
from pydantic import BaseModel, Field
from supabase import Client

from ingestion.embedder import embed_text, get_supabase_client
from security.sanitize import sanitize_text


DEFAULT_TOP_K = 5
DEFAULT_MATCH_THRESHOLD = 0.0
GROQ_CHAT_MODEL = "llama-3.3-70b-versatile"
MATCH_CHUNKS_RPC = "match_transcript_chunks"
PROMPT_INJECTION_PATTERN = re.compile(
    r"\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b",
    re.IGNORECASE,
)


# WHAT THIS DOES: Defines one retrieved transcript chunk returned by vector search.
# WHY THIS MATTERS: The rest of the RAG pipeline can rely on a predictable shape instead of raw DB rows.
class RetrievedChunk(BaseModel):
    """A transcript chunk retrieved from pgvector search."""

    id: Optional[str] = None
    workspace_id: str
    filename: str
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    similarity: float = Field(ge=-1.0, le=1.0)


# WHAT THIS DOES: Defines the final answer object returned by the RAG core.
# WHY THIS MATTERS: API and agent layers can return answers, citations, and source chunks consistently.
class RAGAnswer(BaseModel):
    """Grounded answer plus the chunks used to create it."""

    question: str
    answer: str
    citations: list[str]
    chunks: list[RetrievedChunk]


# WHAT THIS DOES: Defines one meeting row returned by the meetings listing endpoint.
# WHY THIS MATTERS: The API can show a concise list of uploaded meetings without exposing raw chunk rows.
# SECURITY NOTE: This is a read-only summary of validated transcript metadata.
class MeetingSummary(BaseModel):
    """A workspace-scoped summary of one uploaded meeting."""

    workspace_id: str
    filename: str
    filename_hash: str
    meeting_date: Optional[str] = None
    chunk_count: int = Field(ge=1)
    latest_created_at: Optional[str] = None


# WHAT THIS DOES: Embeds a user question and retrieves the most similar transcript chunks.
# WHY THIS MATTERS: This is the core retrieval step of RAG: question meaning becomes a vector search.
def retrieve_relevant_chunks(
    *,
    query: str,
    workspace_id: str,
    top_k: int = DEFAULT_TOP_K,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    client: Client | None = None,
) -> list[RetrievedChunk]:
    """Return the top matching transcript chunks for a workspace."""
    safe_query = sanitize_text(query).strip()
    if not safe_query:
        raise ValueError("query must not be empty")

    if not workspace_id.strip():
        raise ValueError("workspace_id must not be empty")

    if top_k <= 0:
        raise ValueError("top_k must be greater than zero")

    if not -1.0 <= match_threshold <= 1.0:
        raise ValueError("match_threshold must be between -1.0 and 1.0")

    query_embedding = embed_text(safe_query, task_type="retrieval_query")
    supabase = client or get_supabase_client()
    rpc_params = {
        "query_embedding": query_embedding,
        "match_workspace_id": workspace_id,
        "match_count": top_k,
        "match_threshold": match_threshold,
    }

    try:
        response = supabase.rpc(MATCH_CHUNKS_RPC, rpc_params).execute()
    except Exception as exc:
        logger.exception("Supabase vector search failed")
        raise RuntimeError("Unable to retrieve transcript chunks") from exc

    rows = response.data or []
    return [_row_to_chunk(row) for row in rows]


# WHAT THIS DOES: Keeps the old search_memories name as a small wrapper around real retrieval.
# WHY THIS MATTERS: Existing imports can move from placeholder behavior to real search without a big rename.
def search_memories(
    query: str,
    *,
    workspace_id: str,
    top_k: int = DEFAULT_TOP_K,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    """Search meeting memory and return serializable chunk dictionaries."""
    chunks = retrieve_relevant_chunks(
        query=query,
        workspace_id=workspace_id,
        top_k=top_k,
        client=client,
    )
    return [_model_to_dict(chunk) for chunk in chunks]


# WHAT THIS DOES: Lists one row per uploaded meeting for a workspace.
# WHY THIS MATTERS: The UI and API can show the meetings already stored without needing semantic search.
# SECURITY NOTE: The workspace_id is required so one tenant cannot list another tenant's meetings.
def list_meetings(
    *,
    workspace_id: str,
    client: Client | None = None,
) -> list[MeetingSummary]:
    """Return a deduplicated list of meetings for one workspace."""
    if not workspace_id.strip():
        raise ValueError("workspace_id must not be empty")

    supabase = client or get_supabase_client()

    try:
        response = (
            supabase.table("transcript_chunks")
            .select("workspace_id, filename, filename_hash, metadata, created_at")
            .eq("workspace_id", workspace_id)
            .execute()
        )
    except Exception as exc:
        logger.exception("Supabase meeting listing failed")
        raise RuntimeError("Unable to list meetings") from exc

    rows = response.data or []
    grouped_rows: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    for row in rows:
        filename_hash = str(row["filename_hash"])
        current = grouped_rows.get(filename_hash)

        meeting_date = _meeting_date_from_row(row)
        created_at = str(row.get("created_at")) if row.get("created_at") is not None else None

        if current is None:
            grouped_rows[filename_hash] = {
                "workspace_id": str(row["workspace_id"]),
                "filename": str(row["filename"]),
                "filename_hash": filename_hash,
                "meeting_date": meeting_date,
                "chunk_count": 1,
                "latest_created_at": created_at,
            }
            continue

        current["chunk_count"] += 1
        if not current["meeting_date"] and meeting_date:
            current["meeting_date"] = meeting_date
        if created_at and (
            current["latest_created_at"] is None or created_at > current["latest_created_at"]
        ):
            current["latest_created_at"] = created_at

    summaries = [MeetingSummary(**summary) for summary in grouped_rows.values()]
    return sorted(
        summaries,
        key=lambda item: (
            item.latest_created_at or "",
            item.filename.lower(),
        ),
        reverse=True,
    )


# WHAT THIS DOES: Retrieves context and asks Groq to answer using only that context.
# WHY THIS MATTERS: RAG should produce grounded answers with citations instead of relying on model memory.
def answer_question(
    *,
    question: str,
    workspace_id: str,
    top_k: int = DEFAULT_TOP_K,
    client: Client | None = None,
    llm_client: Groq | None = None,
) -> RAGAnswer:
    """Answer a question from retrieved meeting context."""
    safe_question = sanitize_text(question).strip()
    if not safe_question:
        raise ValueError("question must not be empty")

    chunks = retrieve_relevant_chunks(
        query=safe_question,
        workspace_id=workspace_id,
        top_k=top_k,
        client=client,
    )

    if not chunks:
        return RAGAnswer(
            question=safe_question,
            answer="I do not know based on the available meeting transcripts.",
            citations=[],
            chunks=[],
        )

    prompt = build_rag_prompt(question=safe_question, chunks=chunks)
    answer = _call_groq(prompt=prompt, llm_client=llm_client)
    return RAGAnswer(
        question=safe_question,
        answer=answer,
        citations=[_citation_label(chunk) for chunk in chunks],
        chunks=chunks,
    )


# WHAT THIS DOES: Builds the model prompt from the user question and retrieved chunks.
# WHY THIS MATTERS: A strict prompt helps the LLM stay grounded and cite exact meeting sources.
def build_rag_prompt(*, question: str, chunks: list[RetrievedChunk]) -> str:
    """Create a grounded RAG prompt with citation labels."""
    context_blocks = [
        f"[{_citation_label(chunk)}]\n{_sanitize_retrieved_content(chunk.content)}"
        for chunk in chunks
    ]
    context = "\n\n".join(context_blocks)

    return (
        "You are Meeting Memory Agent, an assistant that answers only from the provided "
        "meeting transcript context.\n"
        "If the context does not contain the answer, say you do not know based on the "
        "available meeting transcripts.\n"
        "Cite sources inline using the bracketed source labels exactly as provided.\n\n"
        f"Question:\n{question}\n\n"
        f"Meeting transcript context:\n{context}\n\n"
        "Answer:"
    )


# WHAT THIS DOES: Converts one Supabase RPC row into a validated RetrievedChunk.
# WHY THIS MATTERS: Database responses are external data, so validation catches missing or malformed fields.
def _row_to_chunk(row: dict[str, Any]) -> RetrievedChunk:
    """Validate and sanitize a vector-search row."""
    return RetrievedChunk(
        id=str(row["id"]) if row.get("id") is not None else None,
        workspace_id=str(row["workspace_id"]),
        filename=str(row["filename"]),
        chunk_index=int(row["chunk_index"]),
        content=_sanitize_retrieved_content(str(row["content"])),
        metadata=dict(row.get("metadata") or {}),
        similarity=float(row["similarity"]),
    )


# WHAT THIS DOES: Strips HTML and obvious prompt-injection phrases from retrieved meeting text.
# WHY THIS MATTERS: Retrieved content is untrusted because transcripts can contain malicious instructions.
def _sanitize_retrieved_content(content: str) -> str:
    """Clean transcript content before it reaches the answer prompt."""
    cleaned = sanitize_text(content)
    return PROMPT_INJECTION_PATTERN.sub("[REMOVED_INSTRUCTION]", cleaned).strip()


# WHAT THIS DOES: Creates a compact citation label for one chunk.
# WHY THIS MATTERS: The LLM and UI need a stable source handle to show where an answer came from.
def _citation_label(chunk: RetrievedChunk) -> str:
    """Return a human-readable source label for citation."""
    meeting_date = chunk.metadata.get("meeting_date")
    if meeting_date:
        return f"{chunk.filename}#{chunk.chunk_index} {meeting_date}"

    return f"{chunk.filename}#{chunk.chunk_index}"


# WHAT THIS DOES: Pulls the meeting date from a stored chunk row when one was recorded during ingestion.
# WHY THIS MATTERS: The meetings endpoint can show an actual meeting date when metadata contains it.
# SECURITY NOTE: Metadata is already validated app data; missing fields simply fall back to None.
def _meeting_date_from_row(row: dict[str, Any]) -> Optional[str]:
    """Extract a meeting date string from chunk metadata if available."""
    metadata = row.get("metadata") or {}
    meeting_date = metadata.get("meeting_date")
    if meeting_date is None:
        return None

    return str(meeting_date)


# WHAT THIS DOES: Sends the grounded prompt to Groq's chat completion API.
# WHY THIS MATTERS: This is the generation half of the Phase 2 RAG chain.
def _call_groq(*, prompt: str, llm_client: Groq | None = None) -> str:
    """Call Groq and return the assistant text."""
    client = llm_client or _get_groq_client()

    try:
        response = client.chat.completions.create(
            model=GROQ_CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Answer meeting-memory questions with grounded citations only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
    except Exception as exc:
        logger.exception("Groq answer generation failed")
        raise RuntimeError("Unable to generate RAG answer") from exc

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Groq response did not include answer content")

    return content.strip()


# WHAT THIS DOES: Creates a Groq client using the environment API key.
# WHY THIS MATTERS: Secrets stay in `.env` instead of source code.
def _get_groq_client() -> Groq:
    """Create a Groq client from environment variables."""
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Missing required environment variable: GROQ_API_KEY")

    return Groq(api_key=api_key)


# WHAT THIS DOES: Serializes pydantic models across v1/v2.
# WHY THIS MATTERS: The project can run under either pydantic version while dependencies settle.
def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    """Return a plain dictionary for a pydantic model."""
    if hasattr(model, "model_dump"):
        return model.model_dump()

    return model.dict()
