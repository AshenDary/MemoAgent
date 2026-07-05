"""Persistent security stores for API keys, agent sessions, and audit events."""

from __future__ import annotations

import os
from typing import Any, Protocol

from dotenv import load_dotenv
from loguru import logger
from supabase import Client

from ingestion.embedder import get_supabase_client
from security.auth import StoredAPIKey, model_to_dict
from security.sanitize import sanitize_text


API_KEYS_TABLE = "api_keys"
AGENT_SESSIONS_TABLE = "agent_sessions"
AUDIT_LOGS_TABLE = "audit_logs"


class APIKeyStore(Protocol):
    """Storage contract for hashed API keys."""

    def save(self, record: StoredAPIKey) -> None:
        """Persist one hashed API-key record."""

    def find_active_by_workspace(self, *, workspace_id: str) -> list[StoredAPIKey]:
        """Return active API-key records for one workspace."""


class AgentSessionStore(Protocol):
    """Storage contract for agent session state."""

    def get(self, *, workspace_id: str, session_id: str) -> dict[str, Any]:
        """Return one saved session state."""

    def save(
        self,
        *,
        workspace_id: str,
        session_id: str,
        tool_call_count: int,
        conversation_history: list[str],
    ) -> None:
        """Persist one session state."""


class AuditLogStore(Protocol):
    """Storage contract for safe audit events."""

    def write(
        self,
        *,
        workspace_id: str,
        event_type: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write one audit event."""


class InMemoryAPIKeyStore:
    """Local development API-key store that keeps bcrypt hashes in process memory."""

    def __init__(self) -> None:
        self.records: dict[str, StoredAPIKey] = {}

    def save(self, record: StoredAPIKey) -> None:
        """Store one hashed API key by key id."""
        self.records[record.key_id] = record

    def find_active_by_workspace(self, *, workspace_id: str) -> list[StoredAPIKey]:
        """Return local active API keys for one workspace."""
        return [
            record
            for record in self.records.values()
            if record.workspace_id == workspace_id and record.revoked_at is None
        ]

    def clear(self) -> None:
        """Clear local records for tests."""
        self.records.clear()


class InMemoryAgentSessionStore:
    """Local development agent session store."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}

    def get(self, *, workspace_id: str, session_id: str) -> dict[str, Any]:
        """Return local session state if it exists."""
        return dict(self.sessions.get(_session_key(workspace_id=workspace_id, session_id=session_id), {}))

    def save(
        self,
        *,
        workspace_id: str,
        session_id: str,
        tool_call_count: int,
        conversation_history: list[str],
    ) -> None:
        """Save local session state."""
        self.sessions[_session_key(workspace_id=workspace_id, session_id=session_id)] = {
            "tool_call_count": tool_call_count,
            "conversation_history": conversation_history,
        }

    def clear(self) -> None:
        """Clear local sessions for tests."""
        self.sessions.clear()


class InMemoryAuditLogStore:
    """Local development audit log store."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def write(
        self,
        *,
        workspace_id: str,
        event_type: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append one local audit event."""
        self.events.append(
            {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "event_type": event_type,
                "metadata": metadata or {},
            }
        )

    def clear(self) -> None:
        """Clear local audit events for tests."""
        self.events.clear()


class SupabaseAPIKeyStore:
    """Supabase-backed API-key store that persists bcrypt hashes."""

    def __init__(self, client: Client | None = None) -> None:
        self.client = client or get_supabase_client()

    def save(self, record: StoredAPIKey) -> None:
        """Insert one hashed API-key record into Supabase."""
        payload = {
            "workspace_id": record.workspace_id,
            "key_id": record.key_id,
            "key_hash": record.key_hash,
        }
        try:
            self.client.table(API_KEYS_TABLE).insert(payload).execute()
        except Exception as exc:
            logger.exception("Failed to persist API key hash")
            raise RuntimeError("Unable to persist API key") from exc

    def find_active_by_workspace(self, *, workspace_id: str) -> list[StoredAPIKey]:
        """Load active API-key records for one workspace from Supabase."""
        try:
            response = (
                self.client.table(API_KEYS_TABLE)
                .select("workspace_id, key_id, key_hash, revoked_at")
                .eq("workspace_id", workspace_id)
                .is_("revoked_at", "null")
                .execute()
            )
        except Exception as exc:
            logger.exception("Failed to load API key hashes")
            raise RuntimeError("Unable to load API keys") from exc

        return [
            StoredAPIKey(
                workspace_id=str(row["workspace_id"]),
                key_id=str(row["key_id"]),
                key_hash=str(row["key_hash"]),
                revoked_at=row.get("revoked_at"),
            )
            for row in response.data or []
        ]


class SupabaseAgentSessionStore:
    """Supabase-backed agent session state store."""

    def __init__(self, client: Client | None = None) -> None:
        self.client = client or get_supabase_client()

    def get(self, *, workspace_id: str, session_id: str) -> dict[str, Any]:
        """Load one agent session from Supabase."""
        try:
            response = (
                self.client.table(AGENT_SESSIONS_TABLE)
                .select("tool_call_count, conversation_history")
                .eq("workspace_id", workspace_id)
                .eq("session_id", session_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.exception("Failed to load agent session")
            raise RuntimeError("Unable to load agent session") from exc

        if not response.data:
            return {}

        row = response.data[0]
        return {
            "tool_call_count": int(row.get("tool_call_count") or 0),
            "conversation_history": list(row.get("conversation_history") or []),
        }

    def save(
        self,
        *,
        workspace_id: str,
        session_id: str,
        tool_call_count: int,
        conversation_history: list[str],
    ) -> None:
        """Upsert one agent session into Supabase."""
        payload = {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "tool_call_count": tool_call_count,
            "conversation_history": conversation_history,
        }
        try:
            self.client.table(AGENT_SESSIONS_TABLE).upsert(
                payload,
                on_conflict="workspace_id,session_id",
            ).execute()
        except Exception as exc:
            logger.exception("Failed to persist agent session")
            raise RuntimeError("Unable to persist agent session") from exc


class SupabaseAuditLogStore:
    """Supabase-backed audit log writer."""

    def __init__(self, client: Client | None = None) -> None:
        self.client = client or get_supabase_client()

    def write(
        self,
        *,
        workspace_id: str,
        event_type: str,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert one sanitized audit event into Supabase."""
        payload = {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "event_type": event_type,
            "metadata": _sanitize_metadata(metadata or {}),
        }
        try:
            self.client.table(AUDIT_LOGS_TABLE).insert(payload).execute()
        except Exception as exc:
            logger.exception("Failed to persist audit log")
            raise RuntimeError("Unable to persist audit log") from exc


# WHAT THIS DOES: Chooses Supabase stores when configured, otherwise local in-memory stores.
# WHY THIS WAY: Tests and local demos can run without Supabase, while production persists security state.
# SECURITY NOTE: In-memory fallback never stores plaintext API keys, but it is not durable across restarts.
def build_security_stores() -> tuple[APIKeyStore, AgentSessionStore, AuditLogStore]:
    """Create the configured security stores."""
    load_dotenv()
    if os.getenv("USE_IN_MEMORY_SECURITY_STORE", "").lower() in {"1", "true", "yes"}:
        return InMemoryAPIKeyStore(), InMemoryAgentSessionStore(), InMemoryAuditLogStore()

    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseAPIKeyStore(), SupabaseAgentSessionStore(), SupabaseAuditLogStore()

    if os.getenv("SUPABASE_URL"):
        logger.warning(
            "SUPABASE_URL is set but SUPABASE_SERVICE_ROLE_KEY is missing; using in-memory security stores"
        )

    return InMemoryAPIKeyStore(), InMemoryAgentSessionStore(), InMemoryAuditLogStore()


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Sanitize audit metadata values without logging full private content."""
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        safe_key = sanitize_text(str(key)).strip()
        if not safe_key:
            continue

        if isinstance(value, str):
            sanitized[safe_key] = sanitize_text(value).strip()
        elif isinstance(value, (int, float, bool)) or value is None:
            sanitized[safe_key] = value
        elif isinstance(value, list):
            sanitized[safe_key] = [sanitize_text(str(item)).strip() for item in value[:20]]
        elif isinstance(value, dict):
            sanitized[safe_key] = _sanitize_metadata(value)
        else:
            sanitized[safe_key] = sanitize_text(str(value)).strip()

    return sanitized


def stored_key_to_payload(record: StoredAPIKey) -> dict[str, Any]:
    """Serialize a stored key model for tests and diagnostics."""
    return model_to_dict(record)


def _session_key(*, workspace_id: str, session_id: str) -> str:
    """Return a deterministic local session key."""
    return f"{workspace_id}:{session_id}"
