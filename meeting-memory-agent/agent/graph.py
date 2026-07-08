"""LangGraph entry point for the Phase 3 agentic meeting-memory layer."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from agent.tools import (
    AgentSession,
    answer_from_memory,
    extract_decisions,
    find_action_items,
    list_meetings,
    search_transcripts,
    summarize_meeting,
)
from retrieval.retriever import clean_answer_text
from security.sanitize import sanitize_text


AgentToolName = Literal[
    "search_transcripts",
    "summarize_meeting",
    "extract_decisions",
    "find_action_items",
    "list_meetings",
    "answer_from_memory",
]


class MeetingMemoryState(TypedDict, total=False):
    """State passed through the meeting-memory graph."""

    question: str
    workspace_id: str
    session_id: str
    top_k: int
    meeting_id: str
    start_date: str
    end_date: str
    conversation_history: list[str]
    tool_call_count: int
    selected_tool: AgentToolName
    tool_result: Any
    answer: str
    citations: list[str]
    chunks: list[dict[str, Any]]


# WHAT THIS DOES: Builds a routed LangGraph workflow around the Phase 3 tool set.
# WHY THIS MATTERS: The agent can now choose search, summary, decisions, action items, meeting listing,
# or the normal RAG answer path instead of sending every request through one retrieval chain.
def build_graph() -> Any:
    """Return a compiled routed meeting-memory graph."""
    workflow = StateGraph(MeetingMemoryState)
    workflow.add_node("route", _route_node)
    workflow.add_node("execute_tool", _execute_tool_node)
    workflow.add_node("synthesize", _synthesize_node)
    workflow.set_entry_point("route")
    workflow.add_edge("route", "execute_tool")
    workflow.add_edge("execute_tool", "synthesize")
    workflow.add_edge("synthesize", END)
    return workflow.compile()


# WHAT THIS DOES: Selects a tool from the sanitized user question.
# WHY THIS MATTERS: A deterministic router is easy to test and gives Phase 3 real agent behavior without
# handing tool choice to an LLM before guardrails are in place.
def _route_node(state: MeetingMemoryState) -> MeetingMemoryState:
    """Choose the next tool from the user question."""
    question = sanitize_text(state.get("question", "")).strip()
    lowered = question.lower()

    if any(term in lowered for term in ("action item", "todo", "next step", "assigned")):
        selected_tool: AgentToolName = "find_action_items"
    elif any(term in lowered for term in ("decision", "decided", "approved", "agreed")):
        selected_tool = "extract_decisions"
    elif any(term in lowered for term in ("summarize", "summary", "recap")) and state.get(
        "meeting_id"
    ):
        selected_tool = "summarize_meeting"
    elif any(term in lowered for term in ("list meetings", "available meetings", "meetings do we have")):
        selected_tool = "list_meetings"
    elif any(term in lowered for term in ("search", "find mentions", "show transcript")):
        selected_tool = "search_transcripts"
    else:
        selected_tool = "answer_from_memory"

    return {
        **state,
        "question": question,
        "selected_tool": selected_tool,
    }


# WHAT THIS DOES: Runs exactly one selected tool with workspace, rate-limit, and session state.
# WHY THIS MATTERS: Tool boundaries stay explicit, auditable, and capped per session.
def _execute_tool_node(state: MeetingMemoryState) -> MeetingMemoryState:
    """Execute the selected agent tool."""
    workspace_id = sanitize_text(state.get("workspace_id", "")).strip()
    if not workspace_id:
        raise ValueError("workspace_id must not be empty")

    session = AgentSession(
        session_id=sanitize_text(state.get("session_id", "default")).strip() or "default",
        workspace_id=workspace_id,
        tool_call_count=state.get("tool_call_count", 0),
        conversation_history=state.get("conversation_history", []),
    )
    question = state.get("question", "")
    top_k = state.get("top_k", 5)
    selected_tool = state.get("selected_tool", "answer_from_memory")

    if selected_tool == "search_transcripts":
        tool_result = search_transcripts(
            query=question,
            workspace_id=workspace_id,
            top_k=top_k,
            session=session,
        )
    elif selected_tool == "summarize_meeting":
        tool_result = summarize_meeting(
            meeting_id=state.get("meeting_id", ""),
            workspace_id=workspace_id,
            session=session,
        )
    elif selected_tool == "extract_decisions":
        tool_result = extract_decisions(
            query=question,
            workspace_id=workspace_id,
            top_k=max(top_k, 10),
            session=session,
        )
    elif selected_tool == "find_action_items":
        tool_result = find_action_items(
            query=question,
            workspace_id=workspace_id,
            top_k=max(top_k, 10),
            session=session,
        )
    elif selected_tool == "list_meetings":
        tool_result = list_meetings(
            workspace_id=workspace_id,
            start_date=state.get("start_date"),
            end_date=state.get("end_date"),
            session=session,
        )
    else:
        tool_result = answer_from_memory(
            question=question,
            workspace_id=workspace_id,
            top_k=top_k,
            session=session,
        )

    return {
        **state,
        "tool_result": tool_result,
        "tool_call_count": session.tool_call_count,
        "conversation_history": [*session.conversation_history, question][-10:],
    }


# WHAT THIS DOES: Converts a tool result into the common answer/citation/chunk state shape.
# WHY THIS MATTERS: API callers and future UI work can consume one response shape while tools stay specific.
def _synthesize_node(state: MeetingMemoryState) -> MeetingMemoryState:
    """Create a user-facing answer from the selected tool result."""
    selected_tool = state.get("selected_tool", "answer_from_memory")
    tool_result = state.get("tool_result")

    if selected_tool == "answer_from_memory" and isinstance(tool_result, dict):
        return {
            **state,
            "answer": clean_answer_text(str(tool_result.get("answer", ""))),
            "citations": list(tool_result.get("citations", [])),
            "chunks": list(tool_result.get("chunks", [])),
        }

    if selected_tool == "search_transcripts" and isinstance(tool_result, list):
        citations = [_source_from_chunk(chunk) for chunk in tool_result]
        return {
            **state,
            "answer": f"Found {len(tool_result)} relevant transcript chunks.",
            "citations": citations,
            "chunks": tool_result,
        }

    if selected_tool == "summarize_meeting" and isinstance(tool_result, dict):
        return {
            **state,
            "answer": clean_answer_text(str(tool_result.get("summary", ""))),
            "citations": list(tool_result.get("sources", [])),
            "chunks": [],
        }

    if selected_tool == "extract_decisions" and isinstance(tool_result, dict):
        decisions = list(tool_result.get("decisions", []))
        return {
            **state,
            "answer": clean_answer_text("\n".join(decisions))
            if decisions
            else "I do not know based on the available meeting transcripts.",
            "citations": list(tool_result.get("sources", [])),
            "chunks": [],
        }

    if selected_tool == "find_action_items" and isinstance(tool_result, dict):
        action_items = list(tool_result.get("action_items", []))
        return {
            **state,
            "answer": clean_answer_text("\n".join(action_items))
            if action_items
            else "I do not know based on the available meeting transcripts.",
            "citations": list(tool_result.get("sources", [])),
            "chunks": [],
        }

    if selected_tool == "list_meetings" and isinstance(tool_result, list):
        filenames = [str(meeting.get("filename", "unknown")) for meeting in tool_result]
        return {
            **state,
            "answer": "\n".join(filenames)
            if filenames
            else "No meetings found for this workspace and date range.",
            "citations": [],
            "chunks": [],
        }

    return {
        **state,
        "answer": "I do not know based on the available meeting transcripts.",
        "citations": [],
        "chunks": [],
    }


def _source_from_chunk(chunk: dict[str, Any]) -> str:
    """Build a compact source handle from a serialized chunk."""
    filename = str(chunk.get("filename", "unknown"))
    chunk_index = str(chunk.get("chunk_index", "unknown"))
    metadata = chunk.get("metadata") or {}
    meeting_date = metadata.get("meeting_date")
    if meeting_date:
        return f"source:{filename}:chunk:{chunk_index}:date:{meeting_date}"

    return f"source:{filename}:chunk:{chunk_index}"
