"""Resolve the Weixin human peer without depending on another plugin."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


def _home() -> Path:
    return Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def _context_peers(home: Path, account_id: str) -> set[str]:
    accounts = home / "weixin" / "accounts"
    if account_id:
        candidates = [accounts / f"{account_id}.context-tokens.json"]
    else:
        candidates = sorted(accounts.glob("*.context-tokens.json"))
        if len(candidates) != 1:
            return set()
    try:
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (IndexError, OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    return {
        str(peer).strip()
        for peer, token in payload.items()
        if str(peer or "").strip() and str(token or "").strip()
    }


def _latest_session_peer(home: Path, allowed: set[str] | None) -> str:
    path = Path(os.getenv("HERMES_STATE_DB", str(home / "state.db")))
    if not path.is_file():
        return ""
    try:
        connection = sqlite3.connect(str(path), timeout=2)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT user_id FROM sessions
                WHERE source = 'weixin'
                  AND user_id IS NOT NULL
                  AND TRIM(user_id) != ''
                ORDER BY COALESCE(ended_at, started_at, 0) DESC
                LIMIT 20
                """
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return ""
    for row in rows:
        peer = str(row["user_id"] or "").strip()
        if peer and (allowed is None or peer in allowed):
            return peer
    return ""


def resolve_weixin_peer(configured: str = "", *, account_id: str = "") -> tuple[str, str]:
    """Return a canonical peer and an audit-safe resolution reason."""
    configured = str(configured or "").strip()
    home = _home()
    peers = _context_peers(home, str(account_id or "").strip())
    if configured:
        return configured, "configured"
    latest = _latest_session_peer(home, peers or None)
    if latest:
        return latest, "latest_session"
    if len(peers) == 1:
        return next(iter(peers)), "single_context_peer"
    return "", "unavailable" if not peers else "ambiguous_context_peers"
