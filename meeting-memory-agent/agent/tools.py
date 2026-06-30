"""Tools exposed to the meeting memory agent."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel, Field

from retrieval.retriever import (
    answer_question,
    list_meetings as retrieve_meetings,
    retrieve_meeting_chunks,
    search_memories,
)
from security.sanitize import sanitize_text


MAX_TOOL_CALLS_PER_SESSION = 20


class AgentSession(BaseModel):
    """Tracks bounded tool usage and short conversation context for one agent session."""

    session_id: str
    workspace_id: str
    tool_call_count: int = Field(default=0, ge=0)
    conversation_history: list[str] = Field(default_factory=list)


# WHAT THIS DOES: Lists the currently available meeting-memory tools.
# WHY THIS MATTERS: Phase 3 can use this registry when LangGraph starts routing between tools.
def list_tools() -> list[str]:
    """Return available tool names."""
    return [
        "search_transcripts",
        "summarize_meeting",
        "extract_decisions",
        "find_action_items",
        "list_meetings",
        "answer_from_memory",
    ]


# WHAT THIS DOES: Runs semantic transcript search for a workspace.
# WHY THIS MATTERS: Agent tools should keep tenant boundaries explicit every time they touch stored memory.
def search_transcripts(
    *,
    query: str,
    workspace_id: str,
    top_k: int = 5,
    session: AgentSession | None = None,
) -> list[dict[str, Any]]:
    """Search transcript chunks by semantic similarity."""
    _record_tool_call(session=session, tool_name="search_transcripts")
    return search_memories(query=query, workspace_id=workspace_id, top_k=top_k)


# WHAT THIS DOES: Retrieves relevant chunks and asks the RAG chain for a cited answer.
# WHY THIS MATTERS: This is the tool future agent-routing logic can call for normal user questions.
def answer_from_memory(
    *,
    question: str,
    workspace_id: str,
    top_k: int = 5,
    session: AgentSession | None = None,
) -> dict[str, Any]:
    """Answer a question using the Phase 2 RAG core."""
    _record_tool_call(session=session, tool_name="answer_from_memory")
    result = answer_question(question=question, workspace_id=workspace_id, top_k=top_k)
    if hasattr(result, "model_dump"):
        return result.model_dump()

    return result.dict()


# WHAT THIS DOES: Summarizes one meeting by retrieving chunks scoped to its stored filename hash.
# WHY THIS MATTERS: Phase 3 tools should operate on explicit meeting IDs instead of broad memory searches.
def summarize_meeting(
    *,
    meeting_id: str,
    workspace_id: str,
    session: AgentSession | None = None,
) -> dict[str, Any]:
    """Return a concise extractive summary for one meeting."""
    _record_tool_call(session=session, tool_name="summarize_meeting")
    safe_meeting_id = sanitize_text(meeting_id).strip()
    if not safe_meeting_id:
        raise ValueError("meeting_id must not be empty")

    direct_chunks = retrieve_meeting_chunks(
        meeting_id=safe_meeting_id,
        workspace_id=workspace_id,
    )
    selected_chunks = [_model_to_dict(chunk) for chunk in direct_chunks]
    summary_points = _select_relevant_lines(selected_chunks, keywords=())

    return {
        "meeting_id": safe_meeting_id,
        "summary": " ".join(summary_points)
        if summary_points
        else "I do not know based on the available meeting transcripts.",
        "sources": [_source_from_chunk(chunk) for chunk in selected_chunks[:5]],
    }


# WHAT THIS DOES: Finds decision-like transcript lines through semantic search plus conservative filtering.
# WHY THIS MATTERS: The agent needs a dedicated decisions tool instead of making every question generic RAG.
def extract_decisions(
    *,
    query: str,
    workspace_id: str,
    top_k: int = 10,
    session: AgentSession | None = None,
) -> dict[str, Any]:
    """Extract decision statements from relevant transcript chunks."""
    _record_tool_call(session=session, tool_name="extract_decisions")
    chunks = search_memories(
        query=f"decisions decided approved agreed {query}",
        workspace_id=workspace_id,
        top_k=top_k,
    )
    decisions = _select_relevant_lines(
        chunks,
        keywords=("decided", "decision", "approved", "agreed", "confirmed", "chose"),
    )
    return {
        "decisions": decisions,
        "sources": [_source_from_chunk(chunk) for chunk in chunks[:5]],
    }


# WHAT THIS DOES: Finds action-item-like transcript lines through semantic search plus task wording.
# WHY THIS MATTERS: Action items are a core meeting-memory workflow and deserve a specific agent tool.
def find_action_items(
    *,
    query: str,
    workspace_id: str,
    top_k: int = 10,
    session: AgentSession | None = None,
) -> dict[str, Any]:
    """Extract likely action items from relevant transcript chunks."""
    _record_tool_call(session=session, tool_name="find_action_items")
    chunks = search_memories(
        query=f"action items tasks owners next steps assigned {query}",
        workspace_id=workspace_id,
        top_k=top_k,
    )
    action_items = _select_relevant_lines(
        chunks,
        keywords=("action item", "todo", "next step", "assigned", "owner", "will", "by "),
    )
    return {
        "action_items": action_items,
        "sources": [_source_from_chunk(chunk) for chunk in chunks[:5]],
    }


# WHAT THIS DOES: Lists stored meetings and optionally filters by ISO date range metadata.
# WHY THIS MATTERS: The agent can answer inventory questions without running vector search.
def list_meeting_inventory(
    *,
    workspace_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: AgentSession | None = None,
) -> list[dict[str, Any]]:
    """List available workspace meetings with optional date filtering."""
    _record_tool_call(session=session, tool_name="list_meetings")
    meetings = retrieve_meetings(workspace_id=workspace_id)
    serialized = [_model_to_dict(meeting) for meeting in meetings]
    return [
        meeting
        for meeting in serialized
        if _meeting_in_date_range(
            meeting_date=meeting.get("meeting_date"),
            start_date=start_date,
            end_date=end_date,
        )
    ]


# WHAT THIS DOES: Exposes the project-context tool name while keeping the internal implementation clear.
# WHY THIS MATTERS: LangGraph/tool registries should match the documented Phase 3 tool contract.
def list_meetings(
    *,
    workspace_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: AgentSession | None = None,
) -> list[dict[str, Any]]:
    """List available workspace meetings with optional date filtering."""
    return list_meeting_inventory(
        workspace_id=workspace_id,
        start_date=start_date,
        end_date=end_date,
        session=session,
    )


# WHAT THIS DOES: Enforces the Phase 3 max tool call boundary per session.
# WHY THIS MATTERS: Agent loops need hard limits so a bad route cannot run up API cost.
def _record_tool_call(*, session: AgentSession | None, tool_name: str) -> None:
    """Increment a session tool counter and write an audit log."""
    if session is None:
        logger.info("Agent tool call: tool={} session=none", tool_name)
        return

    if session.tool_call_count >= MAX_TOOL_CALLS_PER_SESSION:
        raise RuntimeError("Tool call limit reached for this session")

    session.tool_call_count += 1
    logger.info(
        "Agent tool call: tool={} session_id={} workspace_id={} count={}",
        tool_name,
        session.session_id,
        session.workspace_id,
        session.tool_call_count,
    )


def _select_relevant_lines(
    chunks: list[dict[str, Any]],
    *,
    keywords: tuple[str, ...],
) -> list[str]:
    """Return sanitized lines that match the requested extraction style."""
    selected: list[str] = []
    for chunk in chunks:
        content = sanitize_text(str(chunk.get("content", "")))
        for line in content.replace("\n", ". ").split(". "):
            safe_line = line.strip()
            if not safe_line:
                continue
            lowered = safe_line.lower()
            if not keywords or any(keyword in lowered for keyword in keywords):
                selected.append(safe_line)
            if len(selected) >= 10:
                return selected

    return selected


def _source_from_chunk(chunk: dict[str, Any]) -> str:
    """Build a compact source handle from a serialized chunk."""
    filename = str(chunk.get("filename", "unknown"))
    chunk_index = str(chunk.get("chunk_index", "unknown"))
    metadata = chunk.get("metadata") or {}
    meeting_date = metadata.get("meeting_date")
    if meeting_date:
        return f"source:{filename}:chunk:{chunk_index}:date:{meeting_date}"

    return f"source:{filename}:chunk:{chunk_index}"


def _meeting_in_date_range(
    *,
    meeting_date: Any,
    start_date: Optional[str],
    end_date: Optional[str],
) -> bool:
    """Return True when a meeting date is within the optional ISO date range."""
    if meeting_date is None:
        return start_date is None and end_date is None

    parsed_meeting_date = date.fromisoformat(str(meeting_date))
    if start_date and parsed_meeting_date < date.fromisoformat(start_date):
        return False
    if end_date and parsed_meeting_date > date.fromisoformat(end_date):
        return False

    return True


def _model_to_dict(model: Any) -> dict[str, Any]:
    """Return a plain dictionary for a pydantic-like model."""
    if hasattr(model, "model_dump"):
        return model.model_dump()

    return model.dict()
