"""LangGraph entry point for the Phase 2 RAG core."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from retrieval.retriever import RAGAnswer, answer_question


class MeetingMemoryState(TypedDict, total=False):
    """State passed through the meeting-memory graph."""

    question: str
    workspace_id: str
    top_k: int
    answer: str
    citations: list[str]
    chunks: list[dict[str, Any]]


# WHAT THIS DOES: Builds a minimal LangGraph workflow around the RAG answer function.
# WHY THIS MATTERS: Phase 2 gets a real graph entry point now, while Phase 3 can add tool routing later.
def build_graph() -> Any:
    """Return a compiled single-node RAG graph."""
    workflow = StateGraph(MeetingMemoryState)
    workflow.add_node("answer_question", _answer_question_node)
    workflow.set_entry_point("answer_question")
    workflow.add_edge("answer_question", END)
    return workflow.compile()


# WHAT THIS DOES: Turns graph state into a RAG call and writes the answer back to state.
# WHY THIS MATTERS: LangGraph nodes should be small, testable units that do one step of the workflow.
def _answer_question_node(state: MeetingMemoryState) -> MeetingMemoryState:
    """Answer one question using retrieved meeting context."""
    question = state.get("question", "").strip()
    workspace_id = state.get("workspace_id", "").strip()
    top_k = state.get("top_k", 5)

    result = answer_question(
        question=question,
        workspace_id=workspace_id,
        top_k=top_k,
    )
    return _answer_to_state(result)


# WHAT THIS DOES: Converts the pydantic RAGAnswer into plain graph state.
# WHY THIS MATTERS: Plain dictionaries are easier for API responses, logs, and future graph nodes to reuse.
def _answer_to_state(answer: RAGAnswer) -> MeetingMemoryState:
    """Serialize a RAG answer into graph state fields."""
    return {
        "answer": answer.answer,
        "citations": answer.citations,
        "chunks": [_model_to_dict(chunk) for chunk in answer.chunks],
    }


# WHAT THIS DOES: Serializes pydantic models across v1/v2.
# WHY THIS MATTERS: It keeps graph code compatible with either pydantic version.
def _model_to_dict(model: Any) -> dict[str, Any]:
    """Return a plain dictionary for a pydantic-like model."""
    if hasattr(model, "model_dump"):
        return model.model_dump()

    return model.dict()
