"""FastAPI entrypoint for meeting memory agent."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel, Field

from agent.graph import build_graph
from ingestion.pipeline import ingest_transcript_file
from ingestion.transcript_loader import ALLOWED_TRANSCRIPT_EXTENSIONS, MAX_TRANSCRIPT_BYTES
from retrieval.retriever import answer_question, clean_answer_text, list_meetings
from security.auth import StoredAPIKey, create_api_key_record, model_to_dict, verify_api_key
from security.sanitize import sanitize_text
from security.rate_limit import build_rate_limiter
from security.stores import build_security_stores

app = FastAPI(title="Meeting Memory Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)
_AGENT_GRAPH = build_graph()
_API_KEY_STORE, _AGENT_SESSION_STORE, _AUDIT_LOG_STORE = build_security_stores()
_AGENT_SESSIONS = _AGENT_SESSION_STORE
_RATE_LIMITER = build_rate_limiter()
ALLOWED_UPLOAD_MIME_TYPES = {
    "",
    "text/plain",
    "text/vtt",
    "application/x-subrip",
    "application/octet-stream",
}


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


class CreateAPIKeyRequest(BaseModel):
    """Request body for creating a workspace API key."""

    workspace_id: str = Field(min_length=1, max_length=128)


class CreateAPIKeyResponse(BaseModel):
    """Response body for a newly created API key."""

    workspace_id: str
    key_id: str
    api_key: str


class UploadResponse(BaseModel):
    """Response body returned after transcript upload ingestion."""

    workspace_id: str
    filename: str
    chunks_stored: int
    message: str


# WHAT THIS DOES: Provides a simple health probe for local/dev hosting checks.
# WHY THIS WAY: A tiny endpoint lets Docker, Railway, and tests confirm the app process is alive.
# SECURITY NOTE: It returns no environment data, versions, or secrets.
@app.get("/health")
def health_check() -> dict[str, str]:
    """Return API health status."""
    return {"status": "ok"}


# WHAT THIS DOES: Creates a workspace API key and stores only its bcrypt hash.
# WHY THIS WAY: The user sees the plaintext key once, while future requests verify against the hash.
# SECURITY NOTE: The plaintext key is returned once; only the bcrypt hash is stored.
@app.post("/auth/create-key", response_model=CreateAPIKeyResponse)
def create_workspace_api_key(http_request: Request, request: CreateAPIKeyRequest) -> CreateAPIKeyResponse:
    """Create a new API key for one workspace."""
    _enforce_rate_limit(client_id=_client_id(http_request), scope="auth:create-key")
    try:
        plaintext_key, record = create_api_key_record(workspace_id=request.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        _API_KEY_STORE.save(record)
        _write_audit_event(
            workspace_id=record.workspace_id,
            event_type="api_key_created",
            metadata={"key_id": record.key_id},
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info("Created API key: workspace_id={} key_id={}", record.workspace_id, record.key_id)
    return CreateAPIKeyResponse(
        workspace_id=record.workspace_id,
        key_id=record.key_id,
        api_key=plaintext_key,
    )


# WHAT THIS DOES: Answers a natural-language question using the Phase 2 RAG core.
# WHY THIS WAY: The API layer stays thin: validate input, sanitize text, call retrieval/generation, serialize.
# SECURITY NOTE: Workspace ID is explicit, question text is sanitized, and internal errors are not leaked.
@app.post("/query", response_model=QueryResponse)
def query_meeting_memory(
    http_request: Request,
    request: QueryRequest,
    x_api_key: Optional[str] = Header(default=None),
) -> QueryResponse:
    """Answer a meeting-memory question for one workspace."""
    safe_workspace_id = sanitize_text(request.workspace_id).strip()
    safe_question = sanitize_text(request.question).strip()

    if not safe_workspace_id or not safe_question:
        raise HTTPException(status_code=422, detail="workspace_id and question are required")

    _require_api_key(workspace_id=safe_workspace_id, api_key=x_api_key)
    _enforce_rate_limit(client_id=_client_id(http_request), scope="query")
    _write_audit_event(
        workspace_id=safe_workspace_id,
        event_type="query_requested",
        metadata={"question_length": len(safe_question), "top_k": request.top_k},
    )

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
        answer=clean_answer_text(result.answer),
        citations=result.citations,
        chunks=[_model_to_dict(chunk) for chunk in result.chunks],
    )


# WHAT THIS DOES: Lists the meetings stored for one workspace.
# WHY THIS WAY: Users need a simple inventory endpoint before they ask follow-up questions.
# SECURITY NOTE: The workspace_id is required, sanitized, and used as the only scope filter.
@app.get("/meetings", response_model=MeetingsResponse)
def get_meetings(
    http_request: Request,
    workspace_id: str,
    x_api_key: Optional[str] = Header(default=None),
) -> MeetingsResponse:
    """Return the meetings available for one workspace."""
    safe_workspace_id = sanitize_text(workspace_id).strip()
    if not safe_workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required")

    _require_api_key(workspace_id=safe_workspace_id, api_key=x_api_key)
    _enforce_rate_limit(client_id=_client_id(http_request), scope="meetings")
    _write_audit_event(
        workspace_id=safe_workspace_id,
        event_type="meetings_listed",
        metadata={},
    )

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
def query_agent(
    http_request: Request,
    request: AgentQueryRequest,
    x_api_key: Optional[str] = Header(default=None),
) -> AgentQueryResponse:
    """Answer a message through the Phase 3 agentic graph."""
    safe_workspace_id = sanitize_text(request.workspace_id).strip()
    safe_message = sanitize_text(request.message).strip()
    safe_session_id = sanitize_text(request.session_id).strip()

    if not safe_workspace_id or not safe_message or not safe_session_id:
        raise HTTPException(status_code=422, detail="workspace_id, session_id, and message are required")

    _require_api_key(workspace_id=safe_workspace_id, api_key=x_api_key)
    _enforce_rate_limit(client_id=_client_id(http_request), scope="agent/query")

    prior_state = _AGENT_SESSION_STORE.get(
        workspace_id=safe_workspace_id,
        session_id=safe_session_id,
    )
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

    _AGENT_SESSION_STORE.save(
        workspace_id=safe_workspace_id,
        session_id=safe_session_id,
        tool_call_count=int(result.get("tool_call_count", 0)),
        conversation_history=list(result.get("conversation_history", [])),
    )
    _write_audit_event(
        workspace_id=safe_workspace_id,
        session_id=safe_session_id,
        event_type="agent_query_completed",
        metadata={
            "selected_tool": str(result.get("selected_tool", "answer_from_memory")),
            "message_length": len(safe_message),
            "tool_call_count": int(result.get("tool_call_count", 0)),
        },
    )

    return AgentQueryResponse(
        session_id=safe_session_id,
        workspace_id=safe_workspace_id,
        selected_tool=str(result.get("selected_tool", "answer_from_memory")),
        answer=clean_answer_text(str(result.get("answer", ""))),
        citations=list(result.get("citations", [])),
        chunks=list(result.get("chunks", [])),
        tool_call_count=int(result.get("tool_call_count", 0)),
        conversation_history=list(result.get("conversation_history", [])),
    )


# WHAT THIS DOES: Accepts a transcript upload, validates it, and sends it through ingestion.
# WHY THIS WAY: Upload is the backend-controlled path from raw meeting file to searchable memory.
# SECURITY NOTE: MIME, extension, and 10MB size checks happen before writing a temp file for ingestion.
@app.post("/upload", response_model=UploadResponse)
async def upload_transcript(
    http_request: Request,
    workspace_id: str = Form(..., min_length=1, max_length=128),
    meeting_date: Optional[str] = Form(default=None, max_length=10),
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(default=None),
) -> UploadResponse:
    """Upload, validate, and ingest one transcript file."""
    safe_workspace_id = sanitize_text(workspace_id).strip()
    if not safe_workspace_id:
        raise HTTPException(status_code=422, detail="workspace_id is required")

    _require_api_key(workspace_id=safe_workspace_id, api_key=x_api_key)
    _enforce_rate_limit(client_id=_client_id(http_request), scope="upload")
    safe_filename = _validate_upload_metadata(file)
    content = await _read_limited_upload(file)
    metadata = {}
    if meeting_date:
        metadata["meeting_date"] = sanitize_text(meeting_date).strip()

    suffix = Path(safe_filename).suffix.lower()
    temp_path: Optional[str] = None
    try:
        with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        records = ingest_transcript_file(
            file_path=temp_path,
            workspace_id=safe_workspace_id,
            metadata=metadata,
            source_filename=safe_filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Transcript upload ingestion failed")
        status_code, detail = _ingestion_failure_response(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)

    _write_audit_event(
        workspace_id=safe_workspace_id,
        event_type="transcript_uploaded",
        metadata={
            "filename": safe_filename,
            "chunks_stored": len(records),
            "file_size_bytes": len(content),
        },
    )

    return UploadResponse(
        workspace_id=safe_workspace_id,
        filename=safe_filename,
        chunks_stored=len(records),
        message="Transcript uploaded and ingested"
        if records
        else "Transcript was already ingested or contained no chunks",
    )


def _require_api_key(*, workspace_id: str, api_key: Optional[str]) -> StoredAPIKey:
    """Authorize one API key for the requested workspace."""
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    try:
        records = _API_KEY_STORE.find_active_by_workspace(workspace_id=workspace_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    for record in records:
        if record.workspace_id != workspace_id:
            continue
        if verify_api_key(api_key=api_key, stored_hash=record.key_hash):
            return record

    raise HTTPException(status_code=403, detail="Invalid API key for workspace")


def _enforce_rate_limit(*, client_id: str, scope: str) -> None:
    """Raise a 429 response when the client exceeds its request budget."""
    result = _RATE_LIMITER.allow(client_id=client_id, scope=scope)
    if result.allowed:
        return

    raise HTTPException(
        status_code=429,
        detail="Rate limit exceeded. Please try again later.",
        headers={"Retry-After": str(result.retry_after_seconds)},
    )


def _write_audit_event(
    *,
    workspace_id: str,
    event_type: str,
    session_id: Optional[str] = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write an audit event without leaking request bodies or transcript content."""
    try:
        _AUDIT_LOG_STORE.write(
            workspace_id=workspace_id,
            session_id=session_id,
            event_type=event_type,
            metadata=metadata or {},
        )
    except RuntimeError:
        logger.exception("Audit logging failed")


def _client_id(request: Optional[Request]) -> str:
    """Return a stable client bucket for local in-memory rate limiting."""
    if request is not None and request.client is not None and request.client.host:
        return request.client.host

    return os.getenv("RATE_LIMIT_CLIENT_ID", "local-client")


def _validate_upload_metadata(file: UploadFile) -> str:
    """Validate upload filename and MIME type before reading bytes."""
    filename = sanitize_text(file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=422, detail="filename is required")

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_TRANSCRIPT_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_TRANSCRIPT_EXTENSIONS))
        raise HTTPException(status_code=415, detail=f"Unsupported transcript format. Allowed: {allowed}")

    content_type = (file.content_type or "").strip().lower()
    if content_type not in ALLOWED_UPLOAD_MIME_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported transcript MIME type")

    return Path(filename).name


def _ingestion_failure_response(exc: Exception) -> tuple[int, str]:
    """Map known ingestion dependency failures to safe client-facing errors."""
    if isinstance(exc, RuntimeError) and str(exc) == "Unable to create Gemini embedding":
        return 503, "Unable to create transcript embeddings"

    return 500, "Unable to ingest transcript"


async def _read_limited_upload(file: UploadFile) -> bytes:
    """Read an upload while enforcing the 10MB transcript limit."""
    content = await file.read(MAX_TRANSCRIPT_BYTES + 1)
    if len(content) > MAX_TRANSCRIPT_BYTES:
        raise HTTPException(status_code=413, detail="Transcript file exceeds the 10MB upload limit")

    if not content.strip():
        raise HTTPException(status_code=422, detail="Transcript file is empty")

    return content


# WHAT THIS DOES: Serializes pydantic chunk models into plain dictionaries for JSON responses.
# WHY THIS WAY: Pydantic v1 and v2 use different model-dump methods, so this keeps the API compatible.
# SECURITY NOTE: Only validated chunk fields are serialized back to the client.
def _model_to_dict(model: Any) -> dict[str, Any]:
    """Return a JSON-ready dictionary for a pydantic-like model."""
    return model_to_dict(model)
