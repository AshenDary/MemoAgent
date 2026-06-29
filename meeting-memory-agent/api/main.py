"""FastAPI entrypoint for meeting memory agent."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from agent.graph import build_graph
from retrieval.retriever import answer_question, list_meetings
from security.sanitize import sanitize_text

app = FastAPI(title="Meeting Memory Agent API")
_AGENT_GRAPH = build_graph()
_AGENT_SESSIONS: dict[str, dict[str, Any]] = {}


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


class AgentQueryRequest(BaseModel):
    """Request body for the Phase 3 routed agent endpoint."""

    workspace_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    top_k: int = Field(default=5, ge=1, le=20)
    meeting_id: Optional[str] = Field(default=None, max_length=256)
    start_date: Optional[str] = Field(default=None, max_length=10)
    end_date: Optional[str] = Field(default=None, max_length=10)


class AgentQueryResponse(BaseModel):
    """Response body returned by the Phase 3 agent endpoint."""

    session_id: str
    workspace_id: str
    selected_tool: str
    answer: str
    citations: list[str]
    chunks: list[dict[str, Any]]
    tool_call_count: int
    conversation_history: list[str]


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


# WHAT THIS DOES: Routes a user message through the Phase 3 LangGraph agent.
# WHY THIS WAY: The API keeps per-session memory and tool-call counts so users can test multi-turn behavior.
# SECURITY NOTE: Workspace/session/message fields are sanitized, and internal tool errors are not leaked.
@app.post("/agent/query", response_model=AgentQueryResponse)
def query_agent(request: AgentQueryRequest) -> AgentQueryResponse:
    """Answer a message through the Phase 3 agentic graph."""
    safe_workspace_id = sanitize_text(request.workspace_id).strip()
    safe_message = sanitize_text(request.message).strip()
    safe_session_id = sanitize_text(request.session_id).strip()

    if not safe_workspace_id or not safe_message or not safe_session_id:
        raise HTTPException(status_code=422, detail="workspace_id, session_id, and message are required")

    session_key = _session_key(workspace_id=safe_workspace_id, session_id=safe_session_id)
    prior_state = _AGENT_SESSIONS.get(session_key, {})
    graph_input: dict[str, Any] = {
        "workspace_id": safe_workspace_id,
        "question": safe_message,
        "session_id": safe_session_id,
        "top_k": request.top_k,
        "tool_call_count": int(prior_state.get("tool_call_count", 0)),
        "conversation_history": list(prior_state.get("conversation_history", [])),
    }

    if request.meeting_id:
        graph_input["meeting_id"] = sanitize_text(request.meeting_id).strip()
    if request.start_date:
        graph_input["start_date"] = sanitize_text(request.start_date).strip()
    if request.end_date:
        graph_input["end_date"] = sanitize_text(request.end_date).strip()

    try:
        result = _AGENT_GRAPH.invoke(graph_input)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        if "Tool call limit reached" in str(exc):
            raise HTTPException(status_code=429, detail="Tool call limit reached for this session") from exc
        logger.exception("Agent query failed")
        raise HTTPException(status_code=500, detail="Unable to answer agent query") from exc
    except Exception as exc:
        logger.exception("Agent query failed")
        raise HTTPException(status_code=500, detail="Unable to answer agent query") from exc

    _AGENT_SESSIONS[session_key] = {
        "tool_call_count": int(result.get("tool_call_count", 0)),
        "conversation_history": list(result.get("conversation_history", [])),
    }

    return AgentQueryResponse(
        session_id=safe_session_id,
        workspace_id=safe_workspace_id,
        selected_tool=str(result.get("selected_tool", "answer_from_memory")),
        answer=str(result.get("answer", "")),
        citations=list(result.get("citations", [])),
        chunks=list(result.get("chunks", [])),
        tool_call_count=int(result.get("tool_call_count", 0)),
        conversation_history=list(result.get("conversation_history", [])),
    )


def _session_key(*, workspace_id: str, session_id: str) -> str:
    """Build a workspace-scoped session key for the in-memory dev session store."""
    return f"{workspace_id}:{session_id}"


# WHAT THIS DOES: Serializes pydantic chunk models into plain dictionaries for JSON responses.
# WHY THIS WAY: Pydantic v1 and v2 use different model-dump methods, so this keeps the API compatible.
# SECURITY NOTE: Only validated chunk fields are serialized back to the client.
def _model_to_dict(model: Any) -> dict[str, Any]:
    """Return a JSON-ready dictionary for a pydantic-like model."""
    if hasattr(model, "model_dump"):
        return model.model_dump()

    return model.dict()
