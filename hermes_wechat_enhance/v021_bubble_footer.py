"""Hermes v0.21 Weixin reliable-delivery compatibility layer.

Adds the old production contract without editing Hermes core: acknowledged
bubble counters/model tags, a ten-bubble context-token budget, a durable FIFO,
silent ``/continue``, and model attribution across interim/final send rails.
"""

from __future__ import annotations

import asyncio
import contextvars
from contextlib import closing
import functools
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from types import MethodType
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

MARKER = "HERMES_WECHAT_V021_RELIABLE_DELIVERY_V2"
FOOTER_RESERVE = 160
MAX_BUBBLES_PER_CONTEXT = 10
QUEUE_CAPACITY_PER_CHAT = 500
DEFAULT_QUEUE_TTL_SECONDS = 72 * 3600

_SEND_CONTEXT: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "hermes_wechat_v021_send_context", default=None
)
_TURN_MODELS: Dict[str, tuple[str, float]] = {}
_TURN_MODELS_LOCK = threading.RLock()


def _safe_model(value: Any) -> str:
    text = str(value or "").strip().replace("`", "").replace("\r", " ").replace("\n", " ")
    return text[:96] or "hermes"


def _chat_key(account_id: str, chat_id: str) -> str:
    return hashlib.sha256(f"{account_id}\0{chat_id}".encode("utf-8")).hexdigest()


def _token_fingerprint(context_token: Optional[str]) -> str:
    return hashlib.sha256(str(context_token or "<tokenless>").encode("utf-8")).hexdigest()


def _runtime_root() -> Path:
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return home / "plugin-data" / "hermes-wechat-enhance"


def _runtime_db_path() -> Path:
    explicit = os.environ.get("HERMES_WECHAT_ENHANCE_RUNTIME_DB", "").strip()
    return Path(explicit).expanduser() if explicit else _runtime_root() / "runtime.sqlite3"


def _extract_text(message: Dict[str, Any]) -> str:
    try:
        from gateway.platforms.weixin import _extract_text as extract

        extracted = str(extract(message.get("item_list") or []) or "")
        if extracted:
            return extracted
    except Exception:
        pass
    parts = []
    for item in message.get("item_list") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("text") or item.get("text_item") or item.get("content") or ""
        if isinstance(value, dict):
            value = value.get("text") or value.get("content") or ""
        if value:
            parts.append(str(value))
    return "\n".join(parts)


def _is_system(metadata: Dict[str, Any]) -> bool:
    if metadata.get("is_system") is True:
        return True
    for key in ("actor", "source", "_delivery_source", "message_origin", "origin"):
        value = str(metadata.get(key) or "").strip().lower()
        if value in {"system", "gateway", "status", "command", "lifecycle", "hermes"}:
            return True
        if any(tag in value for tag in ("startup-ready", "lifecycle")):
            return True
    return False


def _remember_model(chat_id: str, model: Any) -> None:
    normalized = _safe_model(model)
    if not chat_id or normalized == "hermes":
        return
    with _TURN_MODELS_LOCK:
        _TURN_MODELS[str(chat_id)] = (normalized, time.time())


def _known_model(chat_id: str) -> Optional[str]:
    with _TURN_MODELS_LOCK:
        entry = _TURN_MODELS.get(str(chat_id))
        if not entry:
            return None
        model, updated_at = entry
        if time.time() - updated_at > 6 * 3600:
            _TURN_MODELS.pop(str(chat_id), None)
            return None
        return model


def register_turn_model(context: Dict[str, Any]) -> None:
    """Record the actual model emitted by ``agent:end`` for final delivery."""
    if str(context.get("platform") or "").lower() != "weixin":
        return
    _remember_model(
        str(context.get("chat_id") or "").strip(),
        context.get("model_name")
        or context.get("model")
        or context.get("resolved_model")
        or context.get("routed_model"),
    )


def _resolve_model(chat_id: str, metadata: Optional[Dict[str, Any]]) -> str:
    meta = dict(metadata or {})
    if _is_system(meta):
        return "hermes"
    for key in ("model_name", "resolved_model", "routed_model", "model"):
        if meta.get(key):
            return _safe_model(meta[key])
    return _safe_model(_known_model(chat_id))


class DurableRuntime:
    """SQLite-backed budget and FIFO store with ACK-only transitions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._init_lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA secure_delete=ON")
        with self._init_lock:
            if not self._initialized:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS budgets (
                        chat_key TEXT PRIMARY KEY,
                        context_fingerprint TEXT NOT NULL,
                        bubble_count INTEGER NOT NULL DEFAULT 0,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS outbound_queue (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_id TEXT NOT NULL,
                        chat_id TEXT NOT NULL,
                        chat_key TEXT NOT NULL,
                        content TEXT NOT NULL,
                        reply_to TEXT,
                        metadata_json TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        context_fingerprint TEXT NOT NULL,
                        context_token TEXT,
                        client_id TEXT NOT NULL,
                        delivery_id TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        state TEXT NOT NULL DEFAULT 'queued',
                        created_at REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        sent_at REAL,
                        last_error TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_wechat_fifo
                    ON outbound_queue(chat_key, state, seq);
                    """
                )
                self._initialized = True
        self._migrate_counter_json(conn)
        conn.commit()
        return conn

    def _migrate_counter_json(self, conn: sqlite3.Connection) -> None:
        marker = _runtime_root() / ".bubble-counters-v1-migrated"
        source = _runtime_root() / "bubble-counters.json"
        if marker.exists() or not source.exists():
            return
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
            now = time.time()
            for key, entry in entries.items():
                if isinstance(entry, dict):
                    conn.execute(
                        "INSERT OR IGNORE INTO budgets(chat_key,context_fingerprint,bubble_count,updated_at) VALUES(?,?,?,?)",
                        (str(key), str(entry.get("context") or ""), int(entry.get("count", 0) or 0), now),
                    )
            marker.write_text("migrated\n", encoding="utf-8")
        except Exception as exc:
            logger.warning("Hermes WeChat Enhance: counter migration deferred: %s", exc)

    @staticmethod
    def _expire(conn: sqlite3.Connection) -> None:
        now = time.time()
        conn.execute("DELETE FROM outbound_queue WHERE state='queued' AND expires_at<=?", (now,))

    def refresh_context(self, account_id: str, chat_id: str, token: Optional[str]) -> bool:
        key, fingerprint = _chat_key(account_id, chat_id), _token_fingerprint(token)
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT context_fingerprint FROM budgets WHERE chat_key=?", (key,)).fetchone()
            changed = row is None or str(row["context_fingerprint"]) != fingerprint
            if changed:
                conn.execute(
                    "INSERT INTO budgets(chat_key,context_fingerprint,bubble_count,updated_at) VALUES(?,?,0,?) "
                    "ON CONFLICT(chat_key) DO UPDATE SET context_fingerprint=excluded.context_fingerprint,bubble_count=0,updated_at=excluded.updated_at",
                    (key, fingerprint, time.time()),
                )
            return changed

    def snapshot(self, account_id: str, chat_id: str, token: Optional[str]) -> tuple[int, str]:
        self.refresh_context(account_id, chat_id, token)
        key = _chat_key(account_id, chat_id)
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT context_fingerprint,bubble_count FROM budgets WHERE chat_key=?", (key,)
            ).fetchone()
            return int(row["bubble_count"]), str(row["context_fingerprint"])

    def enqueue(
        self, *, account_id: str, chat_id: str, content: str, reply_to: Optional[str],
        metadata: Dict[str, Any], model_name: str, context_token: Optional[str],
        client_id: str, delivery_id: str, chunk_index: int,
    ) -> bool:
        key = _chat_key(account_id, chat_id)
        fingerprint = _token_fingerprint(context_token)
        dedupe_key = f"{delivery_id}:{int(chunk_index)}"
        now = time.time()
        try:
            ttl = int(metadata.get("_delivery_ttl_seconds", DEFAULT_QUEUE_TTL_SECONDS) or DEFAULT_QUEUE_TTL_SECONDS)
        except Exception:
            ttl = DEFAULT_QUEUE_TTL_SECONDS
        ttl = max(60, min(ttl, 30 * 86400))
        with closing(self._connect()) as conn, conn:
            self._expire(conn)
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM outbound_queue WHERE chat_key=? AND state='queued'", (key,)
            ).fetchone()
            if int(pending["n"] or 0) >= QUEUE_CAPACITY_PER_CHAT:
                raise RuntimeError("durable Weixin queue capacity reached")
            try:
                conn.execute(
                    """INSERT INTO outbound_queue(
                        account_id,chat_id,chat_key,content,reply_to,metadata_json,model_name,
                        context_fingerprint,context_token,client_id,delivery_id,chunk_index,
                        dedupe_key,state,created_at,expires_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?)""",
                    (
                        account_id, chat_id, key, content, reply_to,
                        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                        model_name, fingerprint, None, client_id, delivery_id,
                        int(chunk_index), dedupe_key, now, now + ttl,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def peek(self, account_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
        key = _chat_key(account_id, chat_id)
        with closing(self._connect()) as conn, conn:
            self._expire(conn)
            row = conn.execute(
                "SELECT * FROM outbound_queue WHERE chat_key=? AND state='queued' ORDER BY seq LIMIT 1", (key,)
            ).fetchone()
            return dict(row) if row else None

    def mark_error(self, seq: int, error: BaseException) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE outbound_queue SET last_error=? WHERE seq=? AND state='queued'",
                (str(error)[:1000], int(seq)),
            )

    def commit_ack(self, row: Dict[str, Any], count: int, fingerprint: str) -> bool:
        with closing(self._connect()) as conn, conn:
            current = conn.execute(
                "SELECT context_fingerprint,bubble_count FROM budgets WHERE chat_key=?", (row["chat_key"],)
            ).fetchone()
            if current is None or str(current["context_fingerprint"]) != fingerprint:
                return False
            conn.execute(
                "UPDATE budgets SET bubble_count=?,updated_at=? WHERE chat_key=?",
                (max(int(current["bubble_count"] or 0), int(count)), time.time(), row["chat_key"]),
            )
            conn.execute("DELETE FROM outbound_queue WHERE seq=? AND state='queued'", (int(row["seq"]),))
            return True

    def commit_external_ack(
        self, account_id: str, chat_id: str, count: int, fingerprint: str
    ) -> bool:
        """Commit a successfully acknowledged non-text bubble (for example media)."""
        key = _chat_key(account_id, chat_id)
        with closing(self._connect()) as conn, conn:
            current = conn.execute(
                "SELECT context_fingerprint,bubble_count FROM budgets WHERE chat_key=?", (key,)
            ).fetchone()
            if current is None or str(current["context_fingerprint"]) != fingerprint:
                return False
            conn.execute(
                "UPDATE budgets SET bubble_count=?,updated_at=? WHERE chat_key=?",
                (max(int(current["bubble_count"] or 0), int(count)), time.time(), key),
            )
            return True

    def pending_count(self, account_id: str, chat_id: str) -> int:
        key = _chat_key(account_id, chat_id)
        with closing(self._connect()) as conn, conn:
            self._expire(conn)
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM outbound_queue WHERE chat_key=? AND state='queued'", (key,)
            ).fetchone()
            return int(row["n"] or 0)


def _delivery_id(
    account_id: str, chat_id: str, content: str, reply_to: Optional[str],
    metadata: Dict[str, Any], context_token: Optional[str],
) -> str:
    explicit = str(metadata.get("_delivery_id") or metadata.get("delivery_id") or "").strip()
    if explicit:
        return explicit
    anchor = str(metadata.get("reply_to_message_id") or reply_to or "")
    raw = "\0".join((account_id, chat_id, _token_fingerprint(context_token), anchor, content)).encode("utf-8")
    return "auto-" + hashlib.sha256(raw).hexdigest()


def _iter_context_adapters(context: Optional[Dict[str, Any]]) -> Iterable[Any]:
    if not isinstance(context, dict):
        return []
    seen: set[int] = set()
    result = []
    for collection in (context.get("adapters"), context.get("_profile_adapters")):
        if not isinstance(collection, dict):
            continue
        for key, adapter in collection.items():
            key_value = str(getattr(key, "value", key) or "").lower()
            name = str(getattr(adapter, "name", "") or "").lower()
            if key_value != "weixin" and "weixin" not in name:
                continue
            if id(adapter) not in seen:
                seen.add(id(adapter))
                result.append(adapter)
    return result


def patch_gateway_runner(runner: Any) -> bool:
    """Capture the selected model before interim messages start flowing."""
    if runner is None or getattr(runner, "_hermes_wechat_model_route_v2", False):
        return False
    original = getattr(runner, "_resolve_session_agent_runtime", None)
    if not callable(original):
        return False

    @functools.wraps(original)
    def wrapped(*args: Any, **kwargs: Any):
        resolved = original(*args, **kwargs)
        source = kwargs.get("source")
        if source is None:
            source = next((value for value in args if hasattr(value, "chat_id") and hasattr(value, "platform")), None)
        platform_obj = getattr(source, "platform", "")
        platform = str(getattr(platform_obj, "value", platform_obj) or "").lower()
        if platform == "weixin" and isinstance(resolved, tuple) and resolved:
            _remember_model(str(getattr(source, "chat_id", "") or ""), resolved[0])
        return resolved

    runner._resolve_session_agent_runtime = wrapped
    runner._hermes_wechat_model_route_v2 = True
    return True


def patch_adapter(adapter: Any) -> bool:
    if getattr(adapter, "_hermes_wechat_v021_reliable_delivery_v2", False):
        return False
    required = (
        "send", "_send_text_chunk", "_split_text", "_token_store", "_account_id",
        "_process_message", "_send_file", "send_document", "send_video", "send_voice",
    )
    missing = [name for name in required if not hasattr(adapter, name)]
    if missing:
        raise RuntimeError(f"unsupported WeixinAdapter; missing: {', '.join(missing)}")

    original_send = adapter.send
    original_send_text_chunk = adapter._send_text_chunk
    original_split_text = adapter._split_text
    original_process_message = adapter._process_message
    original_send_file = adapter._send_file
    original_send_document = adapter.send_document
    original_send_video = adapter.send_video
    original_send_voice = adapter.send_voice
    runtime = DurableRuntime(_runtime_db_path())
    locks: Dict[str, asyncio.Lock] = {}
    continue_seen: Dict[str, float] = {}

    def split_text(_self: Any, content: str):
        limit = max(1, int(getattr(_self, "MAX_MESSAGE_LENGTH", 2000)) - FOOTER_RESERVE)
        try:
            from gateway.platforms.weixin import _split_text_for_weixin_delivery

            return _split_text_for_weixin_delivery(
                content, limit, bool(getattr(_self, "_split_multiline_messages", False))
            )
        except (ImportError, AttributeError):
            chunks = original_split_text(content)
            return [part for chunk in chunks for part in (chunk[i:i + limit] for i in range(0, len(chunk), limit))]

    async def drain_pending(_self: Any, chat_id: str, *, raise_on_error: bool = False):
        lock = locks.setdefault(str(chat_id), asyncio.Lock())
        sent = 0
        async with lock:
            while True:
                row = runtime.peek(str(getattr(_self, "_account_id", "")), str(chat_id))
                if row is None:
                    break
                current_token = _self._token_store.get(_self._account_id, chat_id)
                count, fingerprint = runtime.snapshot(_self._account_id, chat_id, current_token)
                if count >= MAX_BUBBLES_PER_CONTEXT:
                    break
                next_count = count + 1
                decorated = f"{row['content']}\n\n---\n\n`{next_count}` `{_safe_model(row.get('model_name'))}`"
                try:
                    await original_send_text_chunk(
                        chat_id=str(chat_id), chunk=decorated, context_token=current_token,
                        client_id=str(row["client_id"]),
                    )
                except Exception as exc:
                    runtime.mark_error(int(row["seq"]), exc)
                    logger.warning("Hermes WeChat Enhance: queued send retained after provider failure: %s", exc)
                    if raise_on_error:
                        raise
                    break
                if not runtime.commit_ack(row, next_count, fingerprint):
                    logger.warning("Hermes WeChat Enhance: context changed during ACK; queue item retained")
                    break
                sent += 1
                delay = float(getattr(_self, "_send_chunk_delay_seconds", 0) or 0)
                if delay > 0 and runtime.pending_count(_self._account_id, chat_id):
                    await asyncio.sleep(delay)
        return sent

    async def send_text_chunk(
        _self: Any, *, chat_id: str, chunk: str, context_token: Optional[str], client_id: str,
    ) -> None:
        state = dict(_SEND_CONTEXT.get() or {})
        metadata = dict(state.get("metadata") or {})
        chunk_index = int(state.get("next_chunk_index", 0) or 0)
        state["next_chunk_index"] = chunk_index + 1
        _SEND_CONTEXT.set(state)
        delivery_id = str(state.get("delivery_id") or f"unscoped-{uuid.uuid4().hex}")
        runtime.refresh_context(_self._account_id, chat_id, context_token)
        runtime.enqueue(
            account_id=str(_self._account_id), chat_id=str(chat_id), content=str(chunk),
            reply_to=state.get("reply_to"), metadata=metadata,
            model_name=_safe_model(state.get("model_name")), context_token=context_token,
            client_id=str(client_id), delivery_id=delivery_id, chunk_index=chunk_index,
        )
        await drain_pending(_self, str(chat_id), raise_on_error=True)

    async def send(
        _self: Any, chat_id: str, content: str, reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        meta = dict(metadata or {})
        token_value = _self._token_store.get(_self._account_id, chat_id)
        state = {
            "metadata": meta,
            "model_name": _resolve_model(str(chat_id), meta),
            "reply_to": reply_to,
            "next_chunk_index": 0,
            "delivery_id": _delivery_id(
                str(_self._account_id), str(chat_id), str(content), reply_to, meta, token_value
            ),
        }
        token = _SEND_CONTEXT.set(state)
        try:
            return await original_send(chat_id=chat_id, content=content, reply_to=reply_to, metadata=meta or None)
        finally:
            _SEND_CONTEXT.reset(token)

    async def send_media_with_budget(
        _self: Any, chat_id: str, path: str, caption: Optional[str],
        metadata: Optional[Dict[str, Any]], *, force_file_attachment: bool = False,
    ):
        # Keep the v0.18 production contract: a caption is a normal tagged text
        # bubble, then an acknowledged media item consumes one additional slot.
        if caption:
            caption_result = await _self.send(
                chat_id=chat_id, content=str(caption), metadata=dict(metadata or {}) or None
            )
            if not getattr(caption_result, "success", False):
                return caption_result

        try:
            from gateway.platforms.base import SendResult
        except ImportError:
            from gateway.platforms.weixin import SendResult

        lock = locks.setdefault(str(chat_id), asyncio.Lock())
        async with lock:
            current_token = _self._token_store.get(_self._account_id, chat_id)
            count, fingerprint = runtime.snapshot(_self._account_id, chat_id, current_token)
            if count >= MAX_BUBBLES_PER_CONTEXT:
                return SendResult(success=False, error="context_token budget exhausted; media not sent")
            try:
                message_id = await original_send_file(
                    str(chat_id), str(path), "", force_file_attachment=force_file_attachment
                )
            except Exception as exc:
                return SendResult(success=False, error=str(exc))
            if not runtime.commit_external_ack(
                str(_self._account_id), str(chat_id), count + 1, fingerprint
            ):
                return SendResult(
                    success=False,
                    error="context_token changed during media acknowledgement; delivery state uncertain",
                )
            return SendResult(success=True, message_id=message_id)

    async def send_document(
        _self: Any, chat_id: str, file_path: str, caption: Optional[str] = None,
        file_name: Optional[str] = None, reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None, **kwargs: Any,
    ):
        del file_name, reply_to, kwargs
        if not _self._send_session or not _self._token:
            return await original_send_document(
                chat_id=chat_id, file_path=file_path, caption=caption, metadata=metadata
            )
        return await send_media_with_budget(_self, chat_id, file_path, caption, metadata)

    async def send_video(
        _self: Any, chat_id: str, video_path: str, caption: Optional[str] = None,
        reply_to: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
    ):
        del reply_to
        if not _self._send_session or not _self._token:
            return await original_send_video(
                chat_id=chat_id, video_path=video_path, caption=caption, metadata=metadata
            )
        return await send_media_with_budget(_self, chat_id, video_path, caption, metadata)

    async def send_voice(
        _self: Any, chat_id: str, audio_path: str, caption: Optional[str] = None,
        reply_to: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
    ):
        del reply_to
        if not _self._send_session or not _self._token:
            return await original_send_voice(
                chat_id=chat_id, audio_path=audio_path, caption=caption, metadata=metadata
            )
        return await send_media_with_budget(
            _self, chat_id, audio_path, caption or "[voice message as attachment]",
            metadata, force_file_attachment=True,
        )

    async def process_message(_self: Any, message: Dict[str, Any]):
        sender_id = str(message.get("from_user_id") or "").strip()
        if not sender_id or sender_id == getattr(_self, "_account_id", ""):
            return await original_process_message(message)
        text = _extract_text(message).strip()
        context_token = str(message.get("context_token") or "").strip()
        if context_token:
            await _self._token_store.set(_self._account_id, sender_id, context_token)
            runtime.refresh_context(_self._account_id, sender_id, context_token)
        if text != "/continue":
            return await original_process_message(message)

        message_id = str(message.get("message_id") or "").strip()
        now = time.time()
        for key, seen_at in list(continue_seen.items()):
            if now - seen_at > 24 * 3600:
                continue_seen.pop(key, None)
        if message_id and message_id in continue_seen:
            return None
        if message_id:
            continue_seen[message_id] = now
        sent = await drain_pending(_self, sender_id, raise_on_error=False)
        logger.info(
            "Hermes WeChat Enhance: /continue silently drained=%d pending=%d to=%s",
            sent, runtime.pending_count(_self._account_id, sender_id),
            hashlib.sha256(sender_id.encode()).hexdigest()[:10],
        )
        return None

    adapter._split_text = MethodType(split_text, adapter)
    adapter._send_text_chunk = MethodType(send_text_chunk, adapter)
    adapter.send = MethodType(send, adapter)
    adapter._hermes_wechat_send_media_with_budget_v2 = MethodType(send_media_with_budget, adapter)
    adapter.send_document = MethodType(send_document, adapter)
    adapter.send_video = MethodType(send_video, adapter)
    adapter.send_voice = MethodType(send_voice, adapter)
    adapter._process_message = MethodType(process_message, adapter)
    adapter._hermes_wechat_drain_pending_v2 = MethodType(drain_pending, adapter)
    adapter._hermes_wechat_runtime_v2 = runtime
    adapter._hermes_wechat_v021_reliable_delivery_v2 = True
    adapter._hermes_wechat_v021_bubble_footer_v1 = True
    adapter._hermes_wechat_v021_bubble_footer_originals = {
        "send": original_send, "_send_text_chunk": original_send_text_chunk,
        "_split_text": original_split_text, "_process_message": original_process_message,
        "send_document": original_send_document, "send_video": original_send_video,
        "send_voice": original_send_voice,
    }
    return True


async def install_v021_bubble_footer_hook(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    adapters = list(_iter_context_adapters(context))
    runner = context.get("gateway_runner") if isinstance(context, dict) else None
    if runner is None:
        try:
            from gateway.run import _gateway_runner_ref

            runner = _gateway_runner_ref()
        except Exception as exc:
            logger.error("Hermes WeChat Enhance: gateway runner lookup failed: %s", exc)
    if not adapters and runner is not None:
        adapters = list(_iter_context_adapters({
            "adapters": getattr(runner, "adapters", None),
            "_profile_adapters": getattr(runner, "_profile_adapters", None),
        }))

    model_route_installed = patch_gateway_runner(runner)
    installed = already = 0
    errors = []
    for adapter in adapters:
        try:
            if patch_adapter(adapter):
                installed += 1
            else:
                already += 1
        except Exception as exc:
            errors.append(str(exc))
            logger.exception("Hermes WeChat Enhance: v0.21 compatibility install failed")
    level = logger.warning if installed or already else logger.error
    level(
        "Hermes WeChat Enhance: %s installed=%d already=%d model_route=%s errors=%d",
        MARKER, installed, already, model_route_installed, len(errors),
    )
    return {
        "marker": MARKER, "installed": installed, "already": already,
        "model_route": model_route_installed, "errors": errors,
    }
