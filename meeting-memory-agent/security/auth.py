"""API-key helpers for workspace authentication."""

from __future__ import annotations

import secrets
from typing import Any

import bcrypt
from pydantic import BaseModel, Field

from security.sanitize import sanitize_text


API_KEY_PREFIX = "mma"
API_KEY_BYTES = 32


class StoredAPIKey(BaseModel):
    """Stored API-key record with a bcrypt hash, never plaintext."""

    key_id: str
    workspace_id: str = Field(min_length=1)
    key_hash: str = Field(min_length=1)


# WHAT THIS DOES: Creates a one-time plaintext API key and its bcrypt storage record.
# WHY THIS MATTERS: Users need the raw key once, while the server should only retain the hash.
def create_api_key_record(*, workspace_id: str) -> tuple[str, StoredAPIKey]:
    """Return a plaintext API key plus the hashed record to store server-side."""
    safe_workspace_id = sanitize_text(workspace_id).strip()
    if not safe_workspace_id:
        raise ValueError("workspace_id must not be empty")

    key_id = secrets.token_urlsafe(12)
    plaintext_key = f"{API_KEY_PREFIX}_{key_id}_{secrets.token_urlsafe(API_KEY_BYTES)}"
    return plaintext_key, StoredAPIKey(
        key_id=key_id,
        workspace_id=safe_workspace_id,
        key_hash=hash_api_key(plaintext_key),
    )


# WHAT THIS DOES: Hashes an API key with bcrypt.
# WHY THIS MATTERS: Plaintext API keys must not be stored or compared directly.
def hash_api_key(api_key: str) -> str:
    """Return a bcrypt hash for one API key."""
    safe_key = api_key.strip()
    if not safe_key:
        raise ValueError("api_key must not be empty")

    return bcrypt.hashpw(safe_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# WHAT THIS DOES: Compares a plaintext API key with one stored bcrypt hash.
# WHY THIS MATTERS: bcrypt.checkpw avoids unsafe plaintext comparisons.
def verify_api_key(*, api_key: str, stored_hash: str) -> bool:
    """Return True when an API key matches a stored bcrypt hash."""
    if not api_key.strip() or not stored_hash.strip():
        return False

    try:
        return bcrypt.checkpw(api_key.strip().encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False


def model_to_dict(model: Any) -> dict[str, Any]:
    """Return a plain dictionary for a pydantic-like model."""
    if hasattr(model, "model_dump"):
        return model.model_dump()

    return model.dict()
