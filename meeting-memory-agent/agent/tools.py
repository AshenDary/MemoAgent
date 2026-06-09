"""Tools exposed to the meeting memory agent."""


def list_tools() -> list[str]:
    """Return available tool names."""
    return ["retrieve_memory", "sanitize_input", "load_transcript"]
