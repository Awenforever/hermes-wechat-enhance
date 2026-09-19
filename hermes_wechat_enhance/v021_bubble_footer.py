"""Hermes v0.21 Weixin bubble counters and runtime-model footers.

The v0.21 adapter owns transport retries and durable delivery obligations.  This
module only decorates each physical text bubble at the final adapter boundary,
then commits its counter after the adapter reports a successful send.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import contextvars
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from types import MethodType
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

MARKER = "HERMES_WECHAT_V021_BUBBLE_FOOTER_V1"
FOOTER_RESERVE = 160

_ACTIVE_MODEL: contextvars.ContextVar[str] = contextvars.ContextVar(
    "hermes_wechat_v021_active_model", default="hermes"
)
_TURN_MODELS: Dict[str, str] = {}
_TURN_MODELS_LOCK = threading.RLock()


def _safe_model(value: Any) -> str:
    text = str(value or "").strip().replace("`", "").replace("\r", " ").replace("\n", " ")
    return text[:96] or "hermes"


def _chat_key(account_id: str, chat_id: str) -> str:
    raw = f"{account_id}\0{chat_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _token_fingerprint(context_token: Optional[str]) -> str:
    raw = str(context_token or "<tokenless>").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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


def register_turn_model(context: Dict[str, Any]) -> None:
    """Stage the model reported by ``agent:end`` for the next final send to this peer."""
    if str(context.get("platform") or "").lower() != "weixin":
        return
    chat_id = str(context.get("chat_id") or "").strip()
    model = _safe_model(
        context.get("model_name")
        or context.get("model")
        or context.get("resolved_model")
        or context.get("routed_model")
    )
    if not chat_id or model == "hermes":
        return
    with _TURN_MODELS_LOCK:
        _TURN_MODELS[chat_id] = model


def _peek_turn_model(chat_id: str) -> Optional[str]:
    with _TURN_MODELS_LOCK:
        return _TURN_MODELS.get(chat_id)


def _consume_turn_model(chat_id: str, model: str) -> None:
    with _TURN_MODELS_LOCK:
        if _TURN_MODELS.get(chat_id) == model:
            _TURN_MODELS.pop(chat_id, None)


def _is_system(metadata: Dict[str, Any]) -> bool:
    if metadata.get("is_system") is True:
        return True
    actor = str(metadata.get("actor") or "").strip().lower()
    if actor in {"system", "hermes"}:
        return True
    source = str(metadata.get("source") or metadata.get("_delivery_source") or "").lower()
    return any(tag in source for tag in ("startup-ready", "system", "lifecycle"))


def _resolve_model(chat_id: str, metadata: Optional[Dict[str, Any]]) -> tuple[str, bool]:
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
    pending = _peek_turn_model(chat_id)
    return (_safe_model(pending), True) if pending else ("hermes", False)


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


def _counter_path() -> Path:
    root = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return root / "plugin-data" / "hermes-wechat-enhance" / "bubble-counters.json"


def patch_adapter(adapter: Any) -> bool:
    if getattr(adapter, "_hermes_wechat_v021_bubble_footer_v1", False):
        return False
    required = ("send", "_send_text_chunk", "_split_text", "_token_store", "_account_id")
    missing = [name for name in required if not hasattr(adapter, name)]
    if missing:
        raise RuntimeError(f"unsupported WeixinAdapter; missing: {', '.join(missing)}")

    original_send = adapter.send
    original_send_text_chunk = adapter._send_text_chunk
    original_split_text = adapter._split_text
    store = BubbleCounterStore(_counter_path())
    locks: Dict[str, asyncio.Lock] = {}

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
            count, generation = store.preview(
                str(getattr(_self, "_account_id", "")), str(chat_id), context_token
            )
            model = _safe_model(_ACTIVE_MODEL.get())
            decorated = f"{chunk}\n\n---\n\n`{count}` `{model}`"
            await original_send_text_chunk(
                chat_id=chat_id,
                chunk=decorated,
                context_token=context_token,
                client_id=client_id,
            )
            committed = store.commit(
                str(getattr(_self, "_account_id", "")),
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
        model, staged = _resolve_model(str(chat_id), metadata)
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
        if staged and getattr(result, "success", False):
            _consume_turn_model(str(chat_id), model)
        return result

    adapter._split_text = MethodType(split_text, adapter)
    adapter._send_text_chunk = MethodType(send_text_chunk, adapter)
    adapter.send = MethodType(send, adapter)
    adapter._hermes_wechat_v021_bubble_footer_v1 = True
    adapter._hermes_wechat_v021_bubble_footer_originals = {
        "send": original_send,
        "_send_text_chunk": original_send_text_chunk,
        "_split_text": original_split_text,
    }
    return True


async def install_v021_bubble_footer_hook(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    adapters = list(_iter_context_adapters(context))
    if not adapters:
        try:
            from gateway.run import _gateway_runner_ref

            runner = _gateway_runner_ref()
            adapters = list(
                _iter_context_adapters(
                    {
                        "adapters": getattr(runner, "adapters", None),
                        "_profile_adapters": getattr(runner, "_profile_adapters", None),
                    }
                )
            )
        except Exception as exc:
            logger.error("Hermes WeChat Enhance: v0.21 adapter discovery failed: %s", exc)

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
            logger.exception("Hermes WeChat Enhance: v0.21 bubble footer install failed")
    level = logger.warning if installed or already else logger.error
    level(
        "Hermes WeChat Enhance: %s installed=%d already=%d errors=%d",
        MARKER,
        installed,
        already,
        len(errors),
    )
    return {"marker": MARKER, "installed": installed, "already": already, "errors": errors}
