"""Self-contained JSONL storage for Hermes WeChat enhancement hooks."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# Audit capture is owner-only and size-bounded.  The JSONL store sits outside
# core's ``security.redact_secrets`` egress path, so it hardens itself: 0600 file
# mode, core redaction applied to persisted content, and rotation of the audit
# log (never the pending queue, whose loss would drop undelivered bubbles).
AUDIT_MAX_BYTES = max(0, int(os.environ.get("HERMES_WECHAT_AUDIT_MAX_BYTES", str(5 * 1024 * 1024))))
AUDIT_BACKUP_COUNT = max(0, int(os.environ.get("HERMES_WECHAT_AUDIT_BACKUP_COUNT", "2")))


class MessageStore:
    """Append-only JSONL message store used by Hermes hook handlers."""

    def __init__(self, base_dir: Optional[os.PathLike[str] | str] = None) -> None:
        if base_dir:
            root = Path(base_dir).expanduser()
        else:
            hermes_home = Path(
                os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
            ).expanduser()
            root = hermes_home / "plugin-data" / "hermes-wechat-enhance" / "audit"
        self.base_dir = root
        self.messages_path = root / "messages.jsonl"
        self.pending_path = root / "pending.jsonl"
        self._lock = threading.RLock()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def append(self, message: Dict[str, Any]) -> Dict[str, Any]:
        record = self._normalize_message(message)
        self._append_jsonl(self.messages_path, record, rotate=True)
        return record

    def append_inbound(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self.append(
            {
                "platform": context.get("platform", ""),
                "user_id": context.get("user_id", ""),
                "chat_id": context.get("chat_id", ""),
                "session_id": context.get("session_id", ""),
                "direction": "in",
                "content": context.get("message", ""),
                "model_name": self._extract_model_name(context),
            }
        )

    def append_outbound(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self.append(
            {
                "platform": context.get("platform", ""),
                "user_id": context.get("user_id", ""),
                "chat_id": context.get("chat_id", ""),
                "session_id": context.get("session_id", ""),
                "direction": "out",
                "content": context.get("response", ""),
                "model_name": self._extract_model_name(context),
            }
        )

    def append_pending(self, user_id: str, content: str, **extra: Any) -> Dict[str, Any]:
        record = {
            "message_id": str(extra.pop("message_id", "") or uuid.uuid4()),
            "user_id": user_id,
            "content": self._clip(self._redact(content), 500),
            "timestamp": self._now(),
            **extra,
        }
        self._append_jsonl(self.pending_path, record)
        return record

    def drain_pending(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Remove and return pending records for a user.

        The hook cannot send WeChat messages directly. It returns these records to the
        patched adapter so the adapter can decide whether to skip its local drain.
        """

        user_id = str(user_id or "")
        if not user_id or limit <= 0:
            return []

        with self._lock:
            rows = list(self._read_jsonl(self.pending_path))
            drained: List[Dict[str, Any]] = []
            kept: List[Dict[str, Any]] = []
            for row in rows:
                if row.get("user_id") == user_id and len(drained) < limit:
                    drained.append(row)
                else:
                    kept.append(row)
            self._rewrite_jsonl(self.pending_path, kept)
            return drained

    def query(self, limit: int = 100, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        rows = []
        for row in self._read_jsonl(self.messages_path):
            if user_id is None or row.get("user_id") == user_id:
                rows.append(row)
        return rows[-limit:]

    def stats(self) -> Dict[str, Any]:
        total = inbound = outbound = 0
        by_user: Dict[str, int] = {}
        for row in self._read_jsonl(self.messages_path):
            total += 1
            if row.get("direction") == "in":
                inbound += 1
            elif row.get("direction") == "out":
                outbound += 1
            user_id = str(row.get("user_id") or "")
            if user_id:
                by_user[user_id] = by_user.get(user_id, 0) + 1

        pending_total = sum(1 for _ in self._read_jsonl(self.pending_path))
        return {
            "total": total,
            "inbound": inbound,
            "outbound": outbound,
            "pending": pending_total,
            "users": len(by_user),
            "by_user": by_user,
            "path": str(self.messages_path),
        }

    def footer_metadata(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return optional metadata overrides for message:send.

        Set HERMES_WECHAT_FOOTER_MODEL_NAME to force the footer model name.
        Set HERMES_WECHAT_FOOTER_SYSTEM=1 to mark outgoing content as system-origin.
        """

        metadata: Dict[str, Any] = {}
        model_name = os.environ.get("HERMES_WECHAT_FOOTER_MODEL_NAME", "").strip()
        if model_name:
            metadata["model_name"] = model_name

        is_system = os.environ.get("HERMES_WECHAT_FOOTER_SYSTEM", "").strip().lower()
        if is_system in {"1", "true", "yes", "on"}:
            metadata["is_system"] = True

        return metadata or None

    def _normalize_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "message_id": str(message.get("message_id") or uuid.uuid4()),
            "platform": str(message.get("platform") or ""),
            "user_id": str(message.get("user_id") or ""),
            "chat_id": str(message.get("chat_id") or ""),
            "session_id": str(message.get("session_id") or ""),
            "direction": self._direction(message.get("direction")),
            "content": self._clip(self._redact(message.get("content", "")), 500),
            "timestamp": str(message.get("timestamp") or self._now()),
            "model_name": str(message.get("model_name") or ""),
        }

    def _append_jsonl(self, path: Path, record: Dict[str, Any], *, rotate: bool = False) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if rotate:
                self._rotate_if_needed(path)
            self._ensure_private(path)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _rewrite_jsonl(self, path: Path, rows: Iterable[Dict[str, Any]]) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = Path(f"{path}.tmp")
            fd = os.open(str(tmp_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            os.chmod(tmp_path, 0o600)
            tmp_path.replace(path)

    @staticmethod
    def _ensure_private(path: Path) -> None:
        """Create audit files owner-only (0600) and tighten any pre-existing 0644.

        The production audit log shipped world-readable while every sibling state
        file was 0600, exposing plaintext secrets a user pasted into WeChat to any
        local account.  Best-effort: a chmod failure is logged, never raised, so
        auditing degrades gracefully instead of breaking the send path.
        """
        try:
            if path.exists():
                if path.stat().st_mode & 0o077:
                    os.chmod(path, 0o600)
            else:
                fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
                os.close(fd)
        except OSError as exc:
            logger.warning("Hermes WeChat Enhance: could not enforce 0600 on %s: %s", path.name, exc)

    @staticmethod
    def _rotate_if_needed(path: Path) -> None:
        """Rotate the audit log once it exceeds AUDIT_MAX_BYTES, keeping N backups.

        Only the append-only audit log rotates.  The pending queue must never
        rotate away undelivered bubbles, so callers pass rotate=False for it.
        """
        if AUDIT_MAX_BYTES <= 0 or AUDIT_BACKUP_COUNT <= 0:
            return
        try:
            if not path.exists() or path.stat().st_size <= AUDIT_MAX_BYTES:
                return
            oldest = Path(f"{path}.{AUDIT_BACKUP_COUNT}")
            if oldest.exists():
                oldest.unlink()
            for index in range(AUDIT_BACKUP_COUNT - 1, 0, -1):
                src = Path(f"{path}.{index}")
                if src.exists():
                    src.replace(Path(f"{path}.{index + 1}"))
            path.replace(Path(f"{path}.1"))
        except OSError as exc:
            logger.warning("Hermes WeChat Enhance: audit rotation failed for %s: %s", path.name, exc)

    @staticmethod
    def _redact(value: Any) -> str:
        """Apply core's egress secret redaction before persisting audit content.

        The plugin store is outside core's ``security.redact_secrets`` path, so
        without this a pasted token would be written to disk verbatim.  Falls back
        to the raw text if the core redactor is unavailable so auditing still works.
        """
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        try:
            from agent.redact import redact_for_egress
        except (ImportError, AttributeError):
            return text
        try:
            return redact_for_egress(text)
        except Exception:
            return text


    def _read_jsonl(self, path: Path) -> Iterable[Dict[str, Any]]:
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with self._lock:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        rows.append(value)
        return rows

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clip(value: Any, limit: int) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        return text[:limit]

    @staticmethod
    def _direction(value: Any) -> str:
        return "out" if str(value).lower() == "out" else "in"

    @staticmethod
    def _extract_model_name(context: Dict[str, Any]) -> str:
        metadata = context.get("metadata")
        if isinstance(metadata, dict) and metadata.get("model_name"):
            return str(metadata.get("model_name"))
        if context.get("model_name"):
            return str(context.get("model_name"))
        if context.get("model"):
            return str(context.get("model"))
        return ""
