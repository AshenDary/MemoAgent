"""FastAPI entrypoint for meeting memory agent."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from retrieval.retriever import answer_question, list_meetings
from security.sanitize import sanitize_text

app = FastAPI(title="Meeting Memory Agent API")


class QueryRequest(BaseModel):
    """Request body for asking a workspace-scoped meeting-memory question."""

    workspace_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class QueryResponse(BaseModel):
    """Response body returned by the RAG query endpoint."""

    question: str
    answer: str
    citations: list[str]
    chunks: list[dict[str, Any]]


class MeetingsResponse(BaseModel):
    """Response body for the meetings listing endpoint."""

    workspace_id: str
    meetings: list[dict[str, Any]]


# WHAT THIS DOES: Provides a simple health probe for local/dev hosting checks.
# WHY THIS WAY: A tiny endpoint lets Docker, Railway, and tests confirm the app process is alive.
# SECURITY NOTE: It returns no environment data, versions, or secrets.
@app.get("/health")
def health_check() -> dict[str, str]:
    """Return API health status."""
    return {"status": "ok"}


# WHAT THIS DOES: Answers a natural-language question using the Phase 2 RAG core.
# WHY THIS WAY: The API layer stays thin: validate input, sanitize text, call retrieval/generation, serialize.
# SECURITY NOTE: Workspace ID is explicit, question text is sanitized, and internal errors are not leaked.
@app.post("/query", response_model=QueryResponse)
def query_meeting_memory(request: QueryRequest) -> QueryResponse:
    """Answer a meeting-memory question for one workspace."""
    safe_workspace_id = sanitize_text(request.workspace_id).strip()
    safe_question = sanitize_text(request.question).strip()

    if not safe_workspace_id or not safe_question:
        raise HTTPException(status_code=422, detail="workspace_id and question are required")

    try:
        result = answer_question(
            question=safe_question,
            workspace_id=safe_workspace_id,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("RAG query failed")
        raise HTTPException(status_code=500, detail="Unable to answer query") from exc

    return QueryResponse(
        question=result.question,
        answer=result.answer,
        citations=result.citations,
        chunks=[_model_to_dict(chunk) for chunk in result.chunks],
    )


# WHAT THIS DOES: Lists the meetings stored for one workspace.
# WHY THIS WAY: Users need a simple inventory endpoint before they ask follow-up questions.
# SECURITY NOTE: The workspace_id is required, sanitized, and used as the only scope filter.
@app.get("/meetings", response_model=MeetingsResponse)
def get_meetings(workspace_id: str) -> MeetingsResponse:
    """Return the meetings available for one workspace."""
    safe_workspace_id = sanitize_text(workspace_id).strip()
    if not safe_workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required")

    try:
        meetings = list_meetings(workspace_id=safe_workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Meeting listing failed")
        raise HTTPException(status_code=500, detail="Unable to list meetings") from exc

    return MeetingsResponse(
        workspace_id=safe_workspace_id,
        meetings=[_model_to_dict(meeting) for meeting in meetings],
    )


# WHAT THIS DOES: Serializes pydantic chunk models into plain dictionaries for JSON responses.
# WHY THIS WAY: Pydantic v1 and v2 use different model-dump methods, so this keeps the API compatible.
# SECURITY NOTE: Only validated chunk fields are serialized back to the client.
def _model_to_dict(model: Any) -> dict[str, Any]:
    """Return a JSON-ready dictionary for a pydantic-like model."""
    if hasattr(model, "model_dump"):
        return model.model_dump()

    return model.dict()
