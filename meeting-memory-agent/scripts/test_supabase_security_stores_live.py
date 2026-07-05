"""Run a live CRUD check against the Supabase-backed security stores."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.embedder import get_supabase_client
from security.auth import create_api_key_record, verify_api_key
from security.stores import (
    InMemoryAPIKeyStore,
    InMemoryAgentSessionStore,
    InMemoryAuditLogStore,
    build_security_stores,
)


def main() -> int:
    """Verify live Supabase-backed persistence for security stores."""
    load_dotenv()
    args = _parse_args()

    api_key_store, agent_session_store, audit_log_store = build_security_stores()
    if isinstance(api_key_store, InMemoryAPIKeyStore) or isinstance(agent_session_store, InMemoryAgentSessionStore) or isinstance(audit_log_store, InMemoryAuditLogStore):
        logger.error(
            "Security stores fell back to in-memory. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to run the live check."
        )
        return 1

    client = get_supabase_client()
    workspace_id = args.workspace_id
    session_id = args.session_id
    key_record = None

    try:
        plaintext_key, key_record = create_api_key_record(workspace_id=workspace_id)
        api_key_store.save(key_record)
        stored_key = _fetch_single_row(client, "api_keys", "key_id", key_record.key_id)
        logger.info("Verified API key row for workspace {}", workspace_id)
        if not verify_api_key(api_key=plaintext_key, stored_hash=str(stored_key["key_hash"])):
            raise RuntimeError("Stored API key hash did not validate")

        session_payload = {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "tool_call_count": 2,
            "conversation_history": ["hello", "second turn"],
        }
        agent_session_store.save(**session_payload)
        stored_session = _fetch_single_row(client, "agent_sessions", "session_id", session_id)
        if int(stored_session["tool_call_count"]) != 2:
            raise RuntimeError("Stored session tool_call_count did not persist")
        if list(stored_session["conversation_history"]) != ["hello", "second turn"]:
            raise RuntimeError("Stored session conversation history did not persist")
        logger.info("Verified agent session row for workspace {}", workspace_id)

        audit_log_store.write(
            workspace_id=workspace_id,
            session_id=session_id,
            event_type="live_store_check",
            metadata={"phase": "4", "checked_at": datetime.now(timezone.utc).isoformat()},
        )
        stored_audit = _fetch_single_row(client, "audit_logs", "session_id", session_id)
        if stored_audit["event_type"] != "live_store_check":
            raise RuntimeError("Stored audit event did not persist")
        logger.info("Verified audit log row for workspace {}", workspace_id)
    except Exception as exc:
        logger.error("Live Supabase security-store check failed: {}", exc)
        if not args.keep_data and key_record is not None:
            _cleanup(client, workspace_id=workspace_id, session_id=session_id, key_id=key_record.key_id)
        return 1

    if not args.keep_data and key_record is not None:
        _cleanup(client, workspace_id=workspace_id, session_id=session_id, key_id=key_record.key_id)
        logger.info("Cleaned up live-check rows")

    logger.info("Live Supabase security-store check passed")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a live Supabase security-store check.")
    parser.add_argument("--workspace-id", default=f"phase4_live_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    parser.add_argument("--session-id", default="phase4_live_session")
    parser.add_argument("--keep-data", action="store_true")
    return parser.parse_args()


def _fetch_single_row(client, table_name: str, column_name: str, value: str) -> dict[str, object]:
    response = client.table(table_name).select("*").eq(column_name, value).limit(1).execute()
    if not response.data:
        raise RuntimeError(f"Expected row not found in {table_name}")
    return dict(response.data[0])


def _cleanup(client, *, workspace_id: str, session_id: str, key_id: str) -> None:
    client.table("audit_logs").delete().eq("workspace_id", workspace_id).eq("session_id", session_id).execute()
    client.table("agent_sessions").delete().eq("workspace_id", workspace_id).eq("session_id", session_id).execute()
    client.table("api_keys").delete().eq("key_id", key_id).execute()


if __name__ == "__main__":
    sys.exit(main())