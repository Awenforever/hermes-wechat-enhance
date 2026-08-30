"""Runtime-scoped Weixin slash-command content-dedup exemption.

The official Weixin adapter performs two independent inbound replay checks:
1. provider ``message_id`` replay protection;
2. a sender + text-content fingerprint with a TTL.

The second check incorrectly treats a newly sent, identical slash command as a
replay.  This module leaves provider message-id replay protection intact and
exempts only the exact content-fingerprint lookup for an inbound message whose
normalized text starts with ``/``.

Ownership stays in ``hermes-wechat-enhance``.  No source modification of
``gateway/platforms/weixin.py`` is required.
"""

from __future__ import annotations

import contextvars
import functools
import hashlib
import logging
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

_MARKER = "HERMES_WECHAT_SLASH_COMMAND_DEDUP_HOOK_V1"
# Task-local expected content key.  ContextVar keeps concurrent inbound tasks
# isolated even though they share one adapter-level deduplicator proxy.
_EXPECTED_CONTENT_KEY: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "hermes_wechat_enhance_expected_slash_content_key",
    default=None,
)
_EXPECTED_MESSAGE_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "hermes_wechat_enhance_expected_slash_message_id",
    default=None,
)


class _SlashAwareDeduplicatorProxy:
    """Delegate every operation except the exact slash content-key lookup."""

    def __init__(self, delegate: Any):
        self._delegate = delegate

    def is_duplicate(self, key: Any) -> bool:
        expected = _EXPECTED_CONTENT_KEY.get()
        message_id = _EXPECTED_MESSAGE_ID.get()
        if (
            expected is not None
            and isinstance(key, str)
            and key == expected
            and key != message_id
        ):
            # A fresh provider message_id has already passed through the normal
            # replay guard.  Repeating the command text is intentional control
            # input, not a transport replay.
            return False
        return bool(self._delegate.is_duplicate(key))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


def _extract_text(message: Dict[str, Any]) -> str:
    item_list = message.get("item_list") or []
    try:
        from gateway.platforms.weixin import _extract_text as official_extract_text

        return str(official_extract_text(item_list) or "")
    except Exception:
        # Conservative fallback for compatibility with nearby Hermes builds.
        for item in item_list:
            if not isinstance(item, dict):
                continue
            text_item = item.get("text_item") or {}
            if isinstance(text_item, dict) and text_item.get("text") is not None:
                return str(text_item.get("text") or "")
        return ""


def _content_key(message: Dict[str, Any], text: str) -> Optional[str]:
    sender_id = str(message.get("from_user_id") or "").strip()
    normalized = text.strip()
    if not sender_id or not normalized.startswith("/"):
        return None
    digest = hashlib.md5(text.encode()).hexdigest()
    return f"content:{sender_id}:{digest}"


def patch_weixin_adapter(adapter: Any) -> bool:
    """Patch one live Weixin adapter instance; return True on first install."""

    if getattr(adapter, "_hermes_wechat_slash_dedup_hook_v1", False):
        return False
    original_process = getattr(adapter, "_process_message", None)
    original_dedup = getattr(adapter, "_dedup", None)
    if original_process is None or original_dedup is None:
        raise RuntimeError("Weixin adapter lacks _process_message or _dedup")
    if not callable(getattr(original_dedup, "is_duplicate", None)):
        raise RuntimeError("Weixin adapter deduplicator lacks is_duplicate")

    proxy = _SlashAwareDeduplicatorProxy(original_dedup)

    @functools.wraps(original_process)
    async def _wrapped_process(message: Dict[str, Any]) -> Any:
        text = _extract_text(message)
        expected_key = _content_key(message, text)
        message_id = str(message.get("message_id") or "").strip() or None
        token_key = _EXPECTED_CONTENT_KEY.set(expected_key)
        token_id = _EXPECTED_MESSAGE_ID.set(message_id)
        try:
            return await original_process(message)
        finally:
            _EXPECTED_MESSAGE_ID.reset(token_id)
            _EXPECTED_CONTENT_KEY.reset(token_key)

    adapter._dedup = proxy
    adapter._process_message = _wrapped_process
    adapter._hermes_wechat_slash_dedup_hook_v1 = True
    adapter._hermes_wechat_slash_dedup_original_process = original_process
    adapter._hermes_wechat_slash_dedup_original_dedup = original_dedup
    return True


def _iter_live_weixin_adapters(runner: Any) -> Iterable[Any]:
    seen: set[int] = set()
    collections = [getattr(runner, "adapters", None)]
    profile_adapters = getattr(runner, "_profile_adapters", None)
    if isinstance(profile_adapters, dict):
        collections.extend(profile_adapters.values())

    for collection in collections:
        if not isinstance(collection, dict):
            continue
        for key, adapter in collection.items():
            key_value = getattr(key, "value", key)
            adapter_name = str(getattr(adapter, "name", "")).lower()
            if str(key_value).lower() != "weixin" and "weixin" not in adapter_name:
                continue
            ident = id(adapter)
            if ident in seen:
                continue
            seen.add(ident)
            yield adapter


async def install_slash_command_dedup_hook(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Install the exemption on all live Weixin adapters at gateway startup."""

    del context  # The current gateway startup payload contains platform names only.
    try:
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
    except Exception as exc:
        logger.error("Hermes WeChat Enhance: %s runner lookup failed: %s", _MARKER, exc)
        return {"marker": _MARKER, "installed": 0, "already": 0, "errors": [str(exc)]}

    if runner is None:
        message = "active gateway runner unavailable"
        logger.error("Hermes WeChat Enhance: %s %s", _MARKER, message)
        return {"marker": _MARKER, "installed": 0, "already": 0, "errors": [message]}

    installed = 0
    already = 0
    errors = []
    for adapter in _iter_live_weixin_adapters(runner):
        try:
            if patch_weixin_adapter(adapter):
                installed += 1
            else:
                already += 1
        except Exception as exc:
            errors.append(str(exc))
            logger.exception(
                "Hermes WeChat Enhance: %s adapter patch failed: %s",
                _MARKER,
                exc,
            )

    if installed or already:
        logger.warning(
            "Hermes WeChat Enhance: %s installed=%d already=%d errors=%d",
            _MARKER,
            installed,
            already,
            len(errors),
        )
    else:
        logger.error(
            "Hermes WeChat Enhance: %s no live Weixin adapter found",
            _MARKER,
        )
    return {
        "marker": _MARKER,
        "installed": installed,
        "already": already,
        "errors": errors,
    }
