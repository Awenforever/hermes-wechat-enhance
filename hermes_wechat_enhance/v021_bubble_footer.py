"""Hermes v0.21 Weixin bubble counters and runtime-model footers.

The v0.21 adapter owns transport retries and durable delivery obligations.  This
module decorates physical text bubbles at the final adapter boundary and counts
successful media bubbles even though media intentionally has no textual footer.
Counters are committed only after the adapter reports a successful send.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
import contextvars
import functools
import hashlib
import inspect
import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from types import MethodType
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

MARKER = "HERMES_WECHAT_V021_BUBBLE_FOOTER_V4"
DELIVERY_MARKER = "HERMES_WECHAT_V021_FIFO_CONTEXT_REFRESH_V3"
FOOTER_RESERVE = 160

_ACTIVE_MODEL: contextvars.ContextVar[str] = contextvars.ContextVar(
    "hermes_wechat_v021_active_model", default="hermes"
)
_STREAM_BOUNDARY_MODEL: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "hermes_wechat_v021_stream_boundary_model", default=None
)
_TURN_MODELS: Dict[str, tuple[str, float, bool, str]] = {}
_TURN_MODELS_LOCK = threading.RLock()
TURN_MODEL_TTL_SECONDS = 6 * 3600
MAX_TRANSIENT_DRAIN_RETRIES = 4


def normalize_weixin_inbound_reference(
    message: Dict[str, Any],
    *,
    quote_store: Optional["OutboundQuoteStore"] = None,
    account_id: str = "",
    chat_id: str = "",
) -> Dict[str, Any]:
    """Return current text and quoted-message metadata without concatenating them.

    Tencent places the user's newly typed text in ``text_item.text``.  Older
    clients include the quoted bubble in ``ref_msg.message_item``; newer ones
    may send only ``ref_msg.svr_id`` plus a display ``title``.  Both forms are
    real references and must reach optional plugins as structured metadata.
    """
    item_list = message.get("item_list") or []
    for item in item_list:
        if not isinstance(item, dict) or not isinstance(item.get("text_item"), dict):
            continue
        current_text = str((item.get("text_item") or {}).get("text") or "")
        ref = item.get("ref_msg") if isinstance(item.get("ref_msg"), dict) else {}
        ref_item = ref.get("message_item") if isinstance(ref.get("message_item"), dict) else {}
        ref_text = ""
        if ref_item:
            try:
                from gateway.platforms.weixin import _extract_text

                ref_text = str(_extract_text([ref_item]) or "")
            except Exception:
                nested = ref_item.get("text_item") if isinstance(ref_item.get("text_item"), dict) else {}
                ref_text = str(nested.get("text") or "")
        ref_id = str(
            ref_item.get("msg_id")
            or ref_item.get("message_id")
            or ref.get("svr_id")
            or ref.get("message_id")
            or ""
        )
        title = str(ref.get("title") or "")
        cache_hit = False
        if not ref_text and ref_id and quote_store is not None:
            cached = quote_store.get(account_id, chat_id, ref_id)
            if cached:
                ref_text = cached
                cache_hit = True
        return {
            "text": current_text,
            "reference": {
                "present": bool(ref_item or ref_id or title),
                "message_id": ref_id,
                # A title-only quote is a truncated preview, but retaining it
                # is strictly better than downgrading a real quote to a normal
                # chat message. Consumers must require a unique safe match.
                "text": ref_text or title,
                "title": title,
                "type": ref_item.get("type"),
                "cache_hit": cache_hit,
            },
        }
    return {"text": "", "reference": {"present": False, "message_id": "", "text": "", "title": "", "type": None}}


async def _emit_inbound_action(adapter: Any, message: Dict[str, Any], normalized: Dict[str, Any]) -> bool:
    """Offer an authorized inbound message to independent optional plugins."""
    reference = normalized.get("reference") if isinstance(normalized.get("reference"), dict) else {}
    current_text = str(normalized.get("text") or "")
    # References are always offered as structured events.  Leading @ commands
    # are also offered so an independently installed plugin can claim its own
    # namespace before the conversational agent sees it. Unknown @ commands
    # deliberately fall through unchanged.
    if not reference.get("present") and not current_text.lstrip().startswith("@"):
        return False
    try:
        from gateway.platforms.weixin import _guess_chat_type
        from gateway.run import _gateway_runner_ref

        sender_id = str(message.get("from_user_id") or "").strip()
        chat_type, chat_id = _guess_chat_type(message, getattr(adapter, "_account_id", ""))
        allowed = adapter._is_group_allowed(chat_id) if chat_type == "group" else adapter._is_dm_intake_allowed(sender_id)
        if not allowed:
            return False
        runner = _gateway_runner_ref()
        hooks = getattr(runner, "hooks", None) if runner is not None else None
        if hooks is None:
            return False
        context = {
            "platform": "weixin",
            "authorized": True,
            "authorization_source": "weixin-adapter-allowlist",
            "user_id": sender_id,
            "chat_id": str(chat_id),
            "chat_type": str(chat_type),
            "message_id": str(message.get("message_id") or ""),
            "message": current_text,
            "reference": dict(reference),
        }
        results = await hooks.emit_collect("message:inbound", context)
        for result in results:
            if not isinstance(result, dict) or str(result.get("decision") or "").lower() != "handled":
                continue
            response = str(result.get("message") or "").strip()
            if response:
                metadata = {
                    "is_system": True,
                    "model_name": "hermes",
                    "source": str(result.get("source") or "inbound-action"),
                }
                if result.get("delivery_id"):
                    metadata["_delivery_id"] = str(result["delivery_id"])
                await adapter.send(
                    str(chat_id),
                    response,
                    metadata=metadata,
                )
            return True
    except Exception:
        logger.exception("Hermes WeChat Enhance: optional inbound action dispatch failed")
    return False


async def _set_context_token(store: Any, account_id: str, chat_id: str, token: str) -> None:
    """Support both synchronous and asynchronous Hermes token stores."""
    result = store.set(account_id, chat_id, token)
    if inspect.isawaitable(result):
        await result


def _safe_model(value: Any) -> str:
    text = str(value or "").strip().replace("`", "").replace("\r", " ").replace("\n", " ")
    return text[:96] or "hermes"


def _chat_key(account_id: str, chat_id: str) -> str:
    raw = f"{account_id}\0{chat_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _token_fingerprint(context_token: Optional[str]) -> str:
    raw = str(context_token or "<tokenless>").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _transient_retry_delay(adapter: Any, error: Any, attempt: int) -> Optional[float]:
    """Return a bounded retry delay for transport failures that can self-heal.

    A fresh Weixin Context Token does not clear the adapter's process-wide
    cooldown.  Treating the first cooldown exception as a terminal drain made
    a silent ``/continue`` look ineffective until another inbound message
    happened to arrive.  Permanent/budget failures deliberately return None:
    they must wait for another fresh inbound token instead of retrying forever.
    """
    message = str(error or "")
    folded = message.casefold()
    transient = any(
        marker in folded
        for marker in (
            "cooldown", "rate limit", "rate-limit", "429", "temporar",
            "timeout", "timed out", "connection reset", "connection aborted",
        )
    )
    if not transient:
        return None
    remaining = 0.0
    getter = getattr(adapter, "_rate_limit_cooldown_remaining", None)
    if callable(getter):
        with suppress(Exception):
            remaining = max(0.0, float(getter() or 0.0))
    match = re.search(r"(?:cooldown[^0-9]*|retry(?:ing)?[^0-9]*)([0-9]+(?:\.[0-9]+)?)\s*s", folded)
    if match:
        remaining = max(remaining, float(match.group(1)))
    backoff = min(120.0, 2.0 * (2 ** max(0, int(attempt) - 1)))
    return max(0.05, remaining + 0.25, backoff)


class BubbleCounterStore:
    """Small atomic JSON store; it never persists raw account, peer, or token values."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._loaded = False
        self._entries: Dict[str, Dict[str, Any]] = {}

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            entries = value.get("entries") if isinstance(value, dict) else None
            if isinstance(entries, dict):
                self._entries = {
                    str(key): dict(entry)
                    for key, entry in entries.items()
                    if isinstance(entry, dict)
                }
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning("Hermes WeChat Enhance: bubble counter state unreadable: %s", exc)

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"schema_version": 1, "entries": self._entries}, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with suppress(OSError):
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def preview(self, account_id: str, chat_id: str, context_token: Optional[str]) -> tuple[int, str]:
        key = _chat_key(account_id, chat_id)
        fingerprint = _token_fingerprint(context_token)
        with self._lock:
            self._load()
            entry = self._entries.get(key)
            if not entry or entry.get("context") != fingerprint:
                entry = {"context": fingerprint, "count": 0}
                self._entries[key] = entry
                self._persist()
            return int(entry.get("count", 0) or 0) + 1, fingerprint

    def commit(
        self,
        account_id: str,
        chat_id: str,
        expected_context: str,
        count: int,
    ) -> bool:
        key = _chat_key(account_id, chat_id)
        with self._lock:
            self._load()
            entry = self._entries.get(key)
            if not entry or entry.get("context") != expected_context:
                return False
            entry["count"] = max(int(entry.get("count", 0) or 0), int(count))
            self._persist()
            return True


class PendingBubbleStore:
    """Durable FIFO of physical Weixin bubbles.

    Queueing at this boundary prevents a partially delivered multi-bubble reply
    from being replayed as one large duplicate.  Raw account and peer IDs are
    never persisted; the queued message text is retained because it must later
    be delivered verbatim.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_bubbles (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_key TEXT NOT NULL,
                    chat_key TEXT NOT NULL,
                    client_id TEXT NOT NULL UNIQUE,
                    chunk TEXT NOT NULL,
                    model TEXT NOT NULL,
                    enqueued_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS pending_bubbles_fifo
                ON pending_bubbles(account_key, chat_key, seq);
                """
            )
        with suppress(OSError):
            os.chmod(self.path, 0o600)

    @staticmethod
    def _keys(account_id: str, chat_id: str) -> tuple[str, str]:
        return (_chat_key(account_id, "<account>"), _chat_key(account_id, chat_id))

    def enqueue(self, account_id: str, chat_id: str, client_id: str, chunk: str, model: str, error: str = "") -> int:
        account_key, chat_key = self._keys(account_id, chat_id)
        with self._lock, self._connect() as connection:
            pending = connection.execute(
                "SELECT COUNT(*) FROM pending_bubbles WHERE account_key=? AND chat_key=?",
                (account_key, chat_key),
            ).fetchone()[0]
            if int(pending) >= 500:
                raise RuntimeError("durable Weixin queue capacity reached (500)")
            connection.execute(
                "INSERT OR IGNORE INTO pending_bubbles(account_key,chat_key,client_id,chunk,model,enqueued_at,last_error) VALUES(?,?,?,?,?,?,?)",
                (account_key, chat_key, str(client_id), str(chunk), _safe_model(model), time.time(), str(error)[:500]),
            )
            row = connection.execute(
                "SELECT COUNT(*) FROM pending_bubbles WHERE account_key=? AND chat_key=?",
                (account_key, chat_key),
            ).fetchone()
            return int(row[0])

    def peek(self, account_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
        account_key, chat_key = self._keys(account_id, chat_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM pending_bubbles WHERE account_key=? AND chat_key=? ORDER BY seq LIMIT 1",
                (account_key, chat_key),
            ).fetchone()
            return dict(row) if row else None

    def remove(self, seq: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM pending_bubbles WHERE seq=?", (int(seq),))

    def record_failure(self, seq: int, error: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE pending_bubbles SET attempts=attempts+1,last_error=? WHERE seq=?",
                (str(error)[:500], int(seq)),
            )

    def count(self, account_id: str, chat_id: str) -> int:
        account_key, chat_key = self._keys(account_id, chat_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM pending_bubbles WHERE account_key=? AND chat_key=?",
                (account_key, chat_key),
            ).fetchone()
            return int(row[0])

    def total(self) -> int:
        with self._lock, self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM pending_bubbles").fetchone()[0])


class OutboundQuoteStore:
    """Bounded restart-safe lookup for iLink references that contain only an ID.

    Recent Weixin clients may omit the quoted body and send only ``svr_id``.
    The ID is assigned by the server after an outbound bubble succeeds, so the
    mapping must be captured at the low-level transport response boundary.
    Raw account and conversation identifiers are never persisted.
    """

    RETENTION_SECONDS = 30 * 24 * 3600
    MAX_ROWS_PER_ACCOUNT = 10_000

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._writes = 0
        self._initialize()

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS outbound_quotes (
                    account_key TEXT NOT NULL,
                    chat_key TEXT NOT NULL,
                    server_message_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(account_key, chat_key, server_message_id)
                );
                CREATE INDEX IF NOT EXISTS outbound_quotes_retention
                ON outbound_quotes(account_key, created_at);
                """
            )
            self._prune(connection)
        with suppress(OSError):
            os.chmod(self.path, 0o600)

    @staticmethod
    def _keys(account_id: str, chat_id: str) -> tuple[str, str]:
        return (_chat_key(account_id, "<account>"), _chat_key(account_id, chat_id))

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            "DELETE FROM outbound_quotes WHERE created_at < ?",
            (time.time() - self.RETENTION_SECONDS,),
        )
        accounts = connection.execute(
            "SELECT DISTINCT account_key FROM outbound_quotes"
        ).fetchall()
        for row in accounts:
            connection.execute(
                """
                DELETE FROM outbound_quotes
                WHERE account_key=? AND rowid NOT IN (
                    SELECT rowid FROM outbound_quotes WHERE account_key=?
                    ORDER BY created_at DESC LIMIT ?
                )
                """,
                (row[0], row[0], self.MAX_ROWS_PER_ACCOUNT),
            )

    def put(self, account_id: str, chat_id: str, server_message_id: str, body: str) -> None:
        if not account_id or not chat_id or not server_message_id or not body:
            return
        account_key, chat_key = self._keys(account_id, chat_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO outbound_quotes(account_key,chat_key,server_message_id,body,created_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(account_key,chat_key,server_message_id)
                DO UPDATE SET body=excluded.body,created_at=excluded.created_at
                """,
                (account_key, chat_key, str(server_message_id), str(body), time.time()),
            )
            self._writes += 1
            if self._writes % 100 == 0:
                self._prune(connection)

    def get(self, account_id: str, chat_id: str, server_message_id: str) -> str:
        if not account_id or not chat_id or not server_message_id:
            return ""
        account_key, chat_key = self._keys(account_id, chat_id)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT body FROM outbound_quotes
                WHERE account_key=? AND chat_key=? AND server_message_id=?
                  AND created_at>=?
                """,
                (account_key, chat_key, str(server_message_id), time.time() - self.RETENTION_SECONDS),
            ).fetchone()
            return str(row[0]) if row else ""


def _install_outbound_quote_capture(adapter: Any, store: OutboundQuoteStore) -> bool:
    """Capture server-assigned iLink IDs without patching Hermes source files."""
    try:
        import gateway.platforms.weixin as weixin_module
    except ImportError:
        return False
    low_level = getattr(weixin_module, "_send_message", None)
    if not callable(low_level):
        return False

    registry = getattr(weixin_module, "_hermes_wechat_quote_registry", None)
    if not isinstance(registry, dict):
        registry = {}
        setattr(weixin_module, "_hermes_wechat_quote_registry", registry)
    token = str(getattr(adapter, "_token", "") or "")
    if token:
        registry[hashlib.sha256(token.encode()).hexdigest()] = (
            str(getattr(adapter, "_account_id", "")), store
        )

    if getattr(weixin_module, "_hermes_wechat_quote_capture_installed", False):
        return True
    original = low_level
    signature = inspect.signature(original)

    @functools.wraps(original)
    async def captured_send_message(*args: Any, **kwargs: Any):
        response = await original(*args, **kwargs)
        try:
            bound = signature.bind_partial(*args, **kwargs)
            token_value = str(bound.arguments.get("token") or "")
            chat_id = str(bound.arguments.get("to") or "")
            body = str(bound.arguments.get("text") or "")
            server_id = ""
            if isinstance(response, dict):
                server_id = str(response.get("message_id") or response.get("msg_id") or "")
            else:
                server_id = str(getattr(response, "message_id", "") or "")
            owner = registry.get(hashlib.sha256(token_value.encode()).hexdigest())
            if owner and server_id:
                owner[1].put(owner[0], chat_id, server_id, body)
        except Exception:
            logger.exception("Hermes WeChat Enhance: outbound quote cache write failed")
        return response

    setattr(weixin_module, "_send_message", captured_send_message)
    setattr(weixin_module, "_hermes_wechat_quote_capture_installed", True)
    setattr(weixin_module, "_hermes_wechat_quote_capture_original", original)
    return True


def _response_signature(value: Any) -> str:
    """Stable prefix used only to bind an agent:end result to its final send."""
    return str(value or "").strip()[:500]


def _remember_model(
    chat_id: str,
    model: Any,
    *,
    completed: bool = False,
    response: Any = "",
) -> None:
    normalized = _safe_model(model)
    if not chat_id or normalized == "hermes":
        return
    with _TURN_MODELS_LOCK:
        _TURN_MODELS[str(chat_id)] = (
            normalized,
            time.time(),
            completed,
            _response_signature(response) if completed else "",
        )


def register_turn_model(context: Dict[str, Any]) -> None:
    """Refresh the actual model at ``agent:end`` (including provider fallback)."""
    if str(context.get("platform") or "").lower() != "weixin":
        return
    chat_id = str(context.get("chat_id") or "").strip()
    model = (
        context.get("model_name")
        or context.get("model")
        or context.get("resolved_model")
        or context.get("routed_model")
    )
    response = (
        context.get("response")
        or context.get("final_response")
        or context.get("content")
        or ""
    )
    _remember_model(chat_id, model, completed=True, response=response)


def _peek_turn_model(chat_id: str) -> Optional[tuple[str, bool, str]]:
    with _TURN_MODELS_LOCK:
        entry = _TURN_MODELS.get(str(chat_id))
        if not entry:
            return None
        model, updated_at, completed, response = entry
        if time.time() - updated_at > TURN_MODEL_TTL_SECONDS:
            _TURN_MODELS.pop(str(chat_id), None)
            return None
        return model, completed, response


def _consume_completed_model(chat_id: str, model: str) -> None:
    with _TURN_MODELS_LOCK:
        entry = _TURN_MODELS.get(str(chat_id))
        if entry and entry[0] == model and entry[2]:
            _TURN_MODELS.pop(str(chat_id), None)


def _is_system(metadata: Dict[str, Any]) -> bool:
    if metadata.get("is_system") is True:
        return True
    actor = str(metadata.get("actor") or "").strip().lower()
    if actor in {"system", "hermes"}:
        return True
    source = str(metadata.get("source") or metadata.get("_delivery_source") or "").lower()
    return any(tag in source for tag in ("startup-ready", "system", "lifecycle"))


def _matches_completed_response(content: str, signature: str) -> bool:
    candidate = str(content or "").strip()
    signature = str(signature or "").strip()
    if not candidate or not signature:
        return False
    return candidate.startswith(signature) or signature.startswith(candidate)


def _resolve_model(
    chat_id: str,
    content: str,
    metadata: Optional[Dict[str, Any]],
) -> tuple[str, bool]:
    meta = dict(metadata or {})
    if _is_system(meta):
        return "hermes", False
    explicit = next(
        (
            meta.get(key)
            for key in ("model_name", "resolved_model", "routed_model", "model")
            if meta.get(key)
        ),
        None,
    )
    if explicit:
        return _safe_model(explicit), False
    # Hermes' stream consumer has one exceptional fallback rail for text that
    # precedes an approval/clarification prompt.  That rail calls adapter.send
    # without forwarding the consumer metadata.  patch_stream_consumer scopes
    # the already-proven model origin across that exact call, avoiding both a
    # false ``hermes`` footer and the unsafe chat-wide model inference that used
    # to mislabel approval/progress/lifecycle messages.
    boundary_model = _STREAM_BOUNDARY_MODEL.get()
    if boundary_model:
        return _safe_model(boundary_model), False
    # Unmarked sends are Hermes-owned control traffic by default.  The sole
    # exception is the completed agent result: agent:end supplies both the
    # actual fallback-aware model and a response prefix, which must match the
    # outgoing body.  This prevents approvals, progress heartbeats, command
    # confirmations, errors, and lifecycle notices from borrowing a chat-wide
    # model merely because an agent turn happens to be active.
    pending = _peek_turn_model(chat_id)
    if pending and pending[1] and _matches_completed_response(content, pending[2]):
        return _safe_model(pending[0]), True
    return "hermes", False


def patch_stream_consumer() -> bool:
    """Attach the routed model only to Hermes' model-output transport.

    ``GatewayStreamConsumer`` is the structural boundary for streamed model
    deltas and interim assistant commentary.  Gateway approvals, busy/progress
    notices, command acknowledgements, errors, and lifecycle messages bypass
    this constructor, so they remain conservatively Hermes-owned.
    """
    try:
        from gateway.stream_consumer import GatewayStreamConsumer
    except (ImportError, AttributeError):
        return False
    installed = False
    if not getattr(GatewayStreamConsumer, "_hermes_wechat_model_origin_v1", False):
        original_init = GatewayStreamConsumer.__init__

        @functools.wraps(original_init)
        def wrapped(self: Any, *args: Any, **kwargs: Any) -> None:
            adapter = kwargs.get("adapter") or (args[0] if args else None)
            chat_id = kwargs.get("chat_id") or (args[1] if len(args) > 1 else "")
            name = str(getattr(adapter, "name", "") or "").lower()
            if "weixin" in name:
                pending = _peek_turn_model(str(chat_id))
                if pending and not pending[1]:
                    metadata = dict(kwargs.get("metadata") or {})
                    metadata.update({"actor": "model", "model_name": pending[0]})
                    kwargs["metadata"] = metadata
            original_init(self, *args, **kwargs)

        GatewayStreamConsumer.__init__ = wrapped
        GatewayStreamConsumer._hermes_wechat_model_origin_v1 = True
        installed = True

    # Hermes v0.21's approval/clarification boundary has a fallback send rail
    # that intentionally lives outside the ordinary _send_or_edit path.  Core
    # currently omits metadata on that one adapter.send call.  Carry provenance
    # in a task-local scope around the boundary rather than guessing from text
    # or borrowing the last model for the whole chat.
    boundary_method = getattr(GatewayStreamConsumer, "_finalize_boundary_stream", None)
    if (
        callable(boundary_method)
        and not getattr(GatewayStreamConsumer, "_hermes_wechat_boundary_origin_v2", False)
    ):
        @functools.wraps(boundary_method)
        async def wrapped_boundary(self: Any, *args: Any, **kwargs: Any) -> Any:
            metadata = dict(getattr(self, "metadata", None) or {})
            actor = str(metadata.get("actor") or "").strip().lower()
            model = next(
                (
                    metadata.get(key)
                    for key in ("model_name", "resolved_model", "routed_model", "model")
                    if metadata.get(key)
                ),
                None,
            )
            if actor != "model" or not model:
                return await boundary_method(self, *args, **kwargs)
            token = _STREAM_BOUNDARY_MODEL.set(_safe_model(model))
            try:
                return await boundary_method(self, *args, **kwargs)
            finally:
                _STREAM_BOUNDARY_MODEL.reset(token)

        GatewayStreamConsumer._finalize_boundary_stream = wrapped_boundary
        GatewayStreamConsumer._hermes_wechat_boundary_origin_v2 = True
        installed = True

    return installed


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
    """Capture the selected turn model before any interim Weixin bubble is sent.

    ``agent:end`` is too late for commentary/tool-boundary bubbles.  The gateway
    resolves the effective per-session model before creating its stream consumer,
    so this boundary is both early enough and aware of /model and channel routes.
    The final hook refreshes the value if provider fallback changed the model.
    """
    if runner is None or getattr(runner, "_hermes_wechat_model_route_v4", False):
        return False
    original_resolve = getattr(runner, "_resolve_session_agent_runtime", None)
    original_run = getattr(runner, "_run_agent_inner", None)
    if not callable(original_resolve):
        return False

    @functools.wraps(original_resolve)
    def wrapped(*args: Any, **kwargs: Any):
        resolved = original_resolve(*args, **kwargs)
        source = kwargs.get("source")
        if source is None:
            source = next(
                (value for value in args if hasattr(value, "chat_id") and hasattr(value, "platform")),
                None,
            )
        platform_obj = getattr(source, "platform", "")
        platform = str(getattr(platform_obj, "value", platform_obj) or "").lower()
        if platform == "weixin" and isinstance(resolved, tuple) and resolved:
            _remember_model(str(getattr(source, "chat_id", "") or ""), resolved[0])
        return resolved

    runner._resolve_session_agent_runtime = wrapped
    # ``agent:end`` is emitted from the worker thread and scheduled onto the
    # gateway loop. On a fast non-streaming Weixin turn, the normal final send
    # can beat that hook and arrive without model metadata. Record the completed
    # result synchronously at the runner boundary instead. The result contains
    # the actual post-fallback model selected by Hermes, so this is provenance,
    # not a chat-wide last-model guess.
    if callable(original_run):
        @functools.wraps(original_run)
        async def wrapped_run(*args: Any, **kwargs: Any):
            result = await original_run(*args, **kwargs)
            source = kwargs.get("source")
            if source is None:
                source = next(
                    (value for value in args if hasattr(value, "chat_id") and hasattr(value, "platform")),
                    None,
                )
            platform_obj = getattr(source, "platform", "")
            platform = str(getattr(platform_obj, "value", platform_obj) or "").lower()
            if platform == "weixin" and isinstance(result, dict):
                chat_id = str(getattr(source, "chat_id", "") or "")
                pending = _peek_turn_model(chat_id)
                model = (
                    result.get("model_name")
                    or result.get("model")
                    or result.get("resolved_model")
                    or result.get("routed_model")
                    or (pending[0] if pending else None)
                )
                response = result.get("final_response") or result.get("response") or ""
                _remember_model(chat_id, model, completed=True, response=response)
            return result

        runner._run_agent_inner = wrapped_run
    runner._hermes_wechat_model_route_v4 = True
    return True


def patch_turn_runner_status() -> bool:
    """Mark only direct model-commentary fallback sends as model-authored.

    Weixin cannot edit ordinary messages, so Hermes may fail to construct a
    stream consumer and route ``interim_assistant_cb`` through
    ``TurnRunner._send_status_text``. That method also carries real system
    status traffic, so patching every call would recreate the old "everything
    is the model" defect. The callback supplies a stable semantic call-site
    label; use that structural signal and leave every other status send alone.
    """
    try:
        from gateway.run_turn_runner import TurnRunner
    except (ImportError, AttributeError):
        return False
    if getattr(TurnRunner, "_hermes_wechat_interim_origin_v1", False):
        return False
    original = getattr(TurnRunner, "_send_status_text", None)
    if not callable(original):
        return False

    @functools.wraps(original)
    def wrapped(self: Any, text: str, metadata: Any, log_message: str) -> Any:
        ctx = getattr(self, "_ctx", None)
        source = getattr(ctx, "source", None)
        platform_obj = getattr(source, "platform", "")
        platform = str(getattr(platform_obj, "value", platform_obj) or "").lower()
        if platform == "weixin" and log_message == "interim_assistant_callback scheduling error":
            chat_id = str(getattr(source, "chat_id", "") or "")
            pending = _peek_turn_model(chat_id)
            if pending:
                metadata = dict(metadata or {})
                metadata.update({"actor": "model", "model_name": pending[0]})
        return original(self, text, metadata, log_message)

    TurnRunner._send_status_text = wrapped
    TurnRunner._hermes_wechat_interim_origin_v1 = True
    return True


def _counter_path() -> Path:
    root = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return root / "plugin-data" / "hermes-wechat-enhance" / "bubble-counters.json"


def _queue_path() -> Path:
    root = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return root / "plugin-data" / "hermes-wechat-enhance" / "send-queue.sqlite3"


def _quote_cache_path() -> Path:
    root = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return root / "plugin-data" / "hermes-wechat-enhance" / "quote-cache.sqlite3"


def refresh_runtime_status(context: Optional[Dict[str, Any]] = None) -> None:
    """Refresh live queue observability after startup or an inbound drain."""
    path = _queue_path().parent / "runtime-status.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except Exception:
        value = {}
    adapters = list(_iter_context_adapters(context)) if context else []
    total = 0
    for adapter in adapters:
        queue = getattr(adapter, "_hermes_wechat_v021_pending_queue", None)
        if queue is not None:
            with suppress(Exception):
                total += int(queue.total())
    value["pending_bubbles"] = total
    value["recorded_at"] = time.time()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with suppress(OSError):
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception as exc:
        logger.warning("Hermes WeChat Enhance: runtime receipt refresh failed: %s", exc)


def _normalize_transport_markdown(content: Any) -> str:
    """Normalize Markdown blocks without inserting display-width newlines.

    Weixin performs visual wrapping itself. Hermes v0.21's copy-friendly
    formatter hard-wraps long source lines before delivery, but source
    newlines are semantic Markdown breaks in Weixin. That splits list items
    and even ``[label](url)`` tokens into visibly separated paragraphs.
    Preserve logical lines and leave visual wrapping to the client.
    """
    text = "" if content is None else str(content)
    try:
        from gateway.platforms.weixin import _normalize_markdown_blocks

        return _normalize_markdown_blocks(text)
    except (ImportError, AttributeError):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        output = []
        previous_blank = False
        for raw in text.splitlines():
            line = raw.rstrip()
            blank = not line.strip()
            if blank and previous_blank:
                continue
            output.append("" if blank else line)
            previous_blank = blank
        return "\n".join(output).strip()


def patch_adapter(adapter: Any) -> bool:
    if getattr(adapter, "_hermes_wechat_v021_bubble_footer_v1", False):
        return False
    required = (
        "send", "format_message", "_send_text_chunk", "_split_text", "_process_message",
        "_token_store", "_account_id", "_dedup",
    )
    missing = [name for name in required if not hasattr(adapter, name)]
    if missing:
        raise RuntimeError(f"unsupported WeixinAdapter; missing: {', '.join(missing)}")

    original_send = adapter.send
    original_format_message = adapter.format_message
    original_send_text_chunk = adapter._send_text_chunk
    original_split_text = adapter._split_text
    original_process_message = adapter._process_message
    original_send_file = getattr(adapter, "_send_file", None)
    store = BubbleCounterStore(_counter_path())
    queue = PendingBubbleStore(_queue_path())
    quote_store = OutboundQuoteStore(_quote_cache_path())
    quote_capture = _install_outbound_quote_capture(adapter, quote_store)
    locks: Dict[str, asyncio.Lock] = {}
    retry_tasks: Dict[str, asyncio.Task[Any]] = {}

    def schedule_retry(_self: Any, chat_id: str, error: Any) -> bool:
        key = str(chat_id)
        current = retry_tasks.get(key)
        if current is not None and not current.done():
            return True
        first_delay = _transient_retry_delay(_self, error, 1)
        if first_delay is None:
            return False

        async def retry_worker() -> None:
            delay = first_delay
            try:
                for attempt in range(1, MAX_TRANSIENT_DRAIN_RETRIES + 1):
                    await asyncio.sleep(delay)
                    account_id = str(getattr(_self, "_account_id", ""))
                    if not queue.count(account_id, key):
                        return
                    result = await drain_pending(_self, key)
                    if bool(result.get("ok")) or not int(result.get("pending", 0)):
                        logger.warning(
                            "Hermes WeChat Enhance: deferred FIFO retry recovered peer=%s sent=%d pending=%d",
                            hashlib.sha256(key.encode()).hexdigest()[:12],
                            int(result.get("sent", 0)),
                            int(result.get("pending", 0)),
                        )
                        return
                    next_delay = _transient_retry_delay(
                        _self, result.get("error"), attempt + 1
                    )
                    if next_delay is None:
                        return
                    delay = next_delay
                logger.warning(
                    "Hermes WeChat Enhance: deferred FIFO retries exhausted peer=%s pending=%d; awaiting fresh inbound token",
                    hashlib.sha256(key.encode()).hexdigest()[:12],
                    queue.count(str(getattr(_self, "_account_id", "")), key),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Hermes WeChat Enhance: deferred FIFO retry crashed")
            finally:
                if retry_tasks.get(key) is asyncio.current_task():
                    retry_tasks.pop(key, None)

        retry_tasks[key] = asyncio.create_task(
            retry_worker(), name=f"hermes-wechat-fifo-retry-{hashlib.sha256(key.encode()).hexdigest()[:8]}"
        )
        return True

    def format_message(_self: Any, content: Optional[str]) -> str:
        return _normalize_transport_markdown(content)

    def split_text(_self: Any, content: str):
        limit = max(1, int(getattr(_self, "MAX_MESSAGE_LENGTH", 2000)) - FOOTER_RESERVE)
        try:
            from gateway.platforms.weixin import _split_text_for_weixin_delivery

            return _split_text_for_weixin_delivery(
                content,
                limit,
                bool(getattr(_self, "_split_multiline_messages", False)),
            )
        except (ImportError, AttributeError):
            chunks = original_split_text(content)
            return [
                part
                for chunk in chunks
                for part in (chunk[i : i + limit] for i in range(0, len(chunk), limit))
            ]

    async def send_text_chunk(
        _self: Any,
        *,
        chat_id: str,
        chunk: str,
        context_token: Optional[str],
        client_id: str,
    ) -> None:
        lock = locks.setdefault(str(chat_id), asyncio.Lock())
        async with lock:
            account_id = str(getattr(_self, "_account_id", ""))
            model = _safe_model(_ACTIVE_MODEL.get())
            if queue.count(account_id, str(chat_id)):
                pending = queue.enqueue(account_id, str(chat_id), client_id, chunk, model)
                logger.warning(
                    "Hermes WeChat Enhance: queued bubble behind existing FIFO backlog peer=%s pending=%d",
                    hashlib.sha256(str(chat_id).encode()).hexdigest()[:12],
                    pending,
                )
                return
            count, generation = store.preview(
                account_id, str(chat_id), context_token
            )
            decorated = f"{chunk}\n\n---\n\n`{count}` `{model}`"
            try:
                await original_send_text_chunk(
                    chat_id=chat_id,
                    chunk=decorated,
                    context_token=context_token,
                    client_id=client_id,
                )
            except Exception as exc:
                pending = queue.enqueue(account_id, str(chat_id), client_id, chunk, model, str(exc))
                logger.warning(
                    "Hermes WeChat Enhance: physical bubble queued after delivery failure peer=%s pending=%d error=%s",
                    hashlib.sha256(str(chat_id).encode()).hexdigest()[:12],
                    pending,
                    exc,
                )
                return
            committed = store.commit(
                account_id,
                str(chat_id),
                generation,
                count,
            )
            if not committed:
                logger.warning(
                    "Hermes WeChat Enhance: context changed during acknowledged send; counter not committed"
                )

    async def send(
        _self: Any,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        model, completed = _resolve_model(str(chat_id), content, metadata)
        token = _ACTIVE_MODEL.set(model)
        try:
            result = await original_send(
                chat_id=chat_id,
                content=content,
                reply_to=reply_to,
                metadata=metadata,
            )
        finally:
            _ACTIVE_MODEL.reset(token)
        if completed and getattr(result, "success", False):
            _consume_completed_model(str(chat_id), model)
        return result

    async def send_file(
        _self: Any,
        chat_id: str,
        path: str,
        caption: str,
        force_file_attachment: bool = False,
    ) -> str:
        """Count each acknowledged media bubble at the physical send boundary.

        Hermes runtimes that still pass captions directly to ``_send_file``
        would otherwise send an unnumbered text bubble internally.  Route such
        captions through the normal text path first, then count the media item
        itself without adding a footer to binary content.
        """
        if original_send_file is None:
            raise RuntimeError("unsupported WeixinAdapter; missing: _send_file")
        if caption:
            caption_result = await _self.send(
                chat_id=chat_id,
                content=caption,
                metadata={"is_system": True, "source": "weixin-media-caption"},
            )
            if not getattr(caption_result, "success", False):
                raise RuntimeError(
                    str(getattr(caption_result, "error", "media caption delivery failed"))
                )
        lock = locks.setdefault(str(chat_id), asyncio.Lock())
        async with lock:
            account_id = str(getattr(_self, "_account_id", ""))
            context_token = _self._token_store.get(account_id, str(chat_id))
            count, generation = store.preview(account_id, str(chat_id), context_token)
            message_id = await original_send_file(
                chat_id,
                path,
                "",
                force_file_attachment=force_file_attachment,
            )
            if not store.commit(account_id, str(chat_id), generation, count):
                logger.warning(
                    "Hermes WeChat Enhance: context changed during acknowledged media send; counter not committed"
                )
            return message_id

    async def drain_pending(_self: Any, chat_id: str) -> Dict[str, Any]:
        lock = locks.setdefault(str(chat_id), asyncio.Lock())
        account_id = str(getattr(_self, "_account_id", ""))
        sent = 0
        async with lock:
            while True:
                item = queue.peek(account_id, str(chat_id))
                if not item:
                    break
                context_token = _self._token_store.get(account_id, str(chat_id))
                count, generation = store.preview(account_id, str(chat_id), context_token)
                decorated = f"{item['chunk']}\n\n---\n\n`{count}` `{_safe_model(item['model'])}`"
                try:
                    await original_send_text_chunk(
                        chat_id=str(chat_id),
                        chunk=decorated,
                        context_token=context_token,
                        client_id=str(item["client_id"]),
                    )
                except Exception as exc:
                    queue.record_failure(int(item["seq"]), str(exc))
                    scheduled = schedule_retry(_self, str(chat_id), exc)
                    return {
                        "ok": False,
                        "sent": sent,
                        "pending": queue.count(account_id, str(chat_id)),
                        "error": str(exc),
                        "retry_scheduled": scheduled,
                    }
                if not store.commit(account_id, str(chat_id), generation, count):
                    logger.warning("Hermes WeChat Enhance: context changed during FIFO drain; counter not committed")
                queue.remove(int(item["seq"]))
                sent += 1
        return {"ok": True, "sent": sent, "pending": 0}

    async def process_message(_self: Any, message: Dict[str, Any]) -> Any:
        try:
            from gateway.platforms.weixin import _extract_text, _guess_chat_type
        except ImportError:
            return await original_process_message(message)
        sender_id = str(message.get("from_user_id") or "").strip()
        if not sender_id or sender_id == str(getattr(_self, "_account_id", "")):
            return await original_process_message(message)

        # A fresh context_token accompanies every inbound Weixin message.  Persist
        # it before content/message dedup so even an upstream retry renews the
        # reply window, then resume any durable FIFO backlog with that token.
        context_token = str(message.get("context_token") or "").strip()
        drain_result: Optional[Dict[str, Any]] = None
        if context_token:
            await _set_context_token(_self._token_store, _self._account_id, sender_id, context_token)
            drain_result = await drain_pending(_self, sender_id)
            refresh_runtime_status({"adapters": {"weixin": _self}})

        chat_type, effective_chat_id = _guess_chat_type(message, getattr(_self, "_account_id", ""))
        normalized = normalize_weixin_inbound_reference(
            message,
            quote_store=quote_store,
            account_id=str(getattr(_self, "_account_id", "")),
            chat_id=str(effective_chat_id or sender_id),
        )
        text = str(_extract_text(message.get("item_list") or []) or "")
        if await _emit_inbound_action(_self, message, normalized):
            return None
        if text.strip() != "/continue":
            if drain_result and int(drain_result.get("sent", 0)):
                logger.warning(
                    "Hermes WeChat Enhance: inbound token resumed FIFO peer=%s sent=%d pending=%d ok=%s",
                    hashlib.sha256(sender_id.encode()).hexdigest()[:12],
                    int(drain_result.get("sent", 0)),
                    int(drain_result.get("pending", 0)),
                    bool(drain_result.get("ok")),
                )
            return await original_process_message(message)

        message_id = str(message.get("message_id") or "").strip()
        if message_id and _self._dedup.is_duplicate(message_id):
            return None
        if chat_type == "group":
            if not _self._is_group_allowed(effective_chat_id):
                return None
        elif not _self._is_dm_intake_allowed(sender_id):
            return None
        result = drain_result or await drain_pending(_self, sender_id)
        logger.warning(
            "Hermes WeChat Enhance: /continue handled locally peer=%s sent=%d pending=%d ok=%s",
            hashlib.sha256(sender_id.encode()).hexdigest()[:12],
            int(result.get("sent", 0)),
            int(result.get("pending", 0)),
            bool(result.get("ok")),
        )
        return None

    adapter.format_message = MethodType(format_message, adapter)
    adapter._split_text = MethodType(split_text, adapter)
    adapter._send_text_chunk = MethodType(send_text_chunk, adapter)
    if original_send_file is not None:
        adapter._send_file = MethodType(send_file, adapter)
    adapter.send = MethodType(send, adapter)
    adapter._drain_pending = MethodType(drain_pending, adapter)
    adapter._process_message = MethodType(process_message, adapter)
    adapter._hermes_wechat_v021_pending_queue = queue
    adapter._hermes_wechat_v021_quote_store = quote_store
    adapter._hermes_wechat_v021_quote_capture = quote_capture
    adapter._hermes_wechat_v021_retry_tasks = retry_tasks
    adapter._hermes_wechat_v021_bubble_footer_v1 = True
    adapter._hermes_wechat_v021_bubble_footer_originals = {
        "send": original_send,
        "format_message": original_format_message,
        "_send_text_chunk": original_send_text_chunk,
        "_split_text": original_split_text,
        "_process_message": original_process_message,
        "_send_file": original_send_file,
    }
    return True


async def install_v021_bubble_footer_hook(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    adapters = list(_iter_context_adapters(context))
    runner = None
    try:
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
        if not adapters:
            adapters = list(
                _iter_context_adapters(
                    {
                        "adapters": getattr(runner, "adapters", None),
                        "_profile_adapters": getattr(runner, "_profile_adapters", None),
                    }
                )
            )
    except Exception as exc:
        if not adapters:
            logger.error("Hermes WeChat Enhance: v0.21 adapter discovery failed: %s", exc)

    model_route_installed = patch_gateway_runner(runner)
    stream_origin_installed = patch_stream_consumer()
    interim_origin_installed = patch_turn_runner_status()

    from hermes_wechat_enhance.slash_command_dedup import patch_weixin_adapter

    installed = already = 0
    slash_installed = slash_already = 0
    errors = []
    for adapter in adapters:
        try:
            if patch_adapter(adapter):
                installed += 1
            else:
                already += 1
            # The exemption is part of the live v0.21 startup contract, not a
            # standalone test utility.  Install it after the footer wrapper so
            # its task-local content-key scope reaches the official core
            # _process_message captured by patch_adapter.
            if patch_weixin_adapter(adapter):
                slash_installed += 1
            else:
                slash_already += 1
        except Exception as exc:
            errors.append(str(exc))
            logger.exception("Hermes WeChat Enhance: v0.21 bubble footer install failed")
    level = logger.warning if installed or already else logger.error
    level(
        "Hermes WeChat Enhance: %s installed=%d already=%d slash_installed=%d "
        "slash_already=%d model_route=%s errors=%d",
        MARKER,
        installed,
        already,
        slash_installed,
        slash_already,
        model_route_installed,
        len(errors),
    )
    pending = 0
    for adapter in adapters:
        queue = getattr(adapter, "_hermes_wechat_v021_pending_queue", None)
        if queue is not None:
            with suppress(Exception):
                pending += int(queue.total())
    result = {
        "marker": MARKER,
        "delivery_marker": DELIVERY_MARKER,
        "installed": installed,
        "already": already,
        "slash_dedup_installed": slash_installed,
        "slash_dedup_already": slash_already,
        "model_route": model_route_installed,
        "stream_origin": stream_origin_installed,
        "interim_origin": interim_origin_installed,
        "errors": errors,
        "capabilities": {
            "bubble_footer": True,
            "durable_fifo": True,
            "continue_intercept": True,
            "all_inbound_context_refresh": True,
            "turn_model_before_interim": True,
            "stream_boundary_model_origin": True,
            "nonstream_interim_model_origin": True,
            "pre_delivery_final_model_origin": True,
            "fresh_slash_command_content_dedup_exemption": True,
        },
        "pending_bubbles": pending,
        "recorded_at": time.time(),
    }
    try:
        path = _queue_path().parent / "runtime-status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with suppress(OSError):
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception as exc:
        logger.warning("Hermes WeChat Enhance: runtime receipt write failed: %s", exc)
    return result
