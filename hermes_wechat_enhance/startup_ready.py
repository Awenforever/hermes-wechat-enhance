"""WeChat startup-ready lifecycle notification."""

from __future__ import annotations

import logging
import os
from typing import Any


logger = logging.getLogger(__name__)

READY_NOTIFY_ENV = "HERMES_WEIXIN_STARTUP_READY_NOTIFY"
READY_MESSAGE_ENV = "HERMES_WEIXIN_STARTUP_READY_MESSAGE"
DEFAULT_READY_MESSAGE = "Gateway online — Hermes is back and ready"
_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


def startup_ready_enabled() -> bool:
    """Return whether the gateway startup notification should be sent."""
    value = os.getenv(READY_NOTIFY_ENV, "1").strip().lower()
    return value not in _FALSE_VALUES


def startup_ready_message() -> str:
    return os.getenv(READY_MESSAGE_ENV, DEFAULT_READY_MESSAGE).strip() or DEFAULT_READY_MESSAGE


def weixin_metadata() -> dict[str, Any]:
    return {
        "is_system": True,
        "actor": "system",
        "origin": "lifecycle",
        "message_origin": "lifecycle",
        "model_name": "hermes",
        "resolved_model": "hermes",
        "routed_model": "hermes",
        "model": "hermes",
    }


def is_weixin_platform(platform: Any) -> bool:
    return str(getattr(platform, "value", platform)).lower() == "weixin"


def find_weixin_adapter(adapters: dict[Any, Any]) -> Any | None:
    for platform, adapter in (adapters or {}).items():
        if is_weixin_platform(platform):
            return adapter
    return None


def configured_home_channel(config: Any) -> str:
    """Resolve WeChat home channel from GatewayConfig, then env fallbacks."""
    try:
        from gateway.config import Platform

        home = config.get_home_channel(Platform.WEIXIN) if config is not None else None
        chat_id = getattr(home, "chat_id", "") if home else ""
        if chat_id:
            return str(chat_id).strip()
    except Exception:
        logger.debug("Hermes WeChat Enhance: config home channel lookup failed", exc_info=True)

    for env_name in (
        "HERMES_WEIXIN_HOME_CHANNEL",
        "WEIXIN_HOME_CHANNEL",
        "HERMES_PROACTIVE_WEIXIN_CHAT_ID",
    ):
        chat_id = os.getenv(env_name, "").strip()
        if chat_id:
            return chat_id
    return ""


async def send_startup_ready_notification(context: dict[str, Any] | None = None) -> bool:
    """Send the one-shot WeChat gateway-ready message on gateway:startup."""
    if not startup_ready_enabled():
        logger.info("Hermes WeChat Enhance: startup ready notification disabled")
        return False

    try:
        from gateway.run import _gateway_runner_ref
    except ImportError as exc:
        logger.warning("Hermes WeChat Enhance: gateway import failed: %s", exc)
        return False

    runner = _gateway_runner_ref()
    if runner is None:
        logger.warning("Hermes WeChat Enhance: no gateway runner for startup notification")
        return False

    adapter = find_weixin_adapter(getattr(runner, "adapters", {}))
    if adapter is None:
        logger.warning("Hermes WeChat Enhance: no WeChat adapter for startup notification")
        return False

    chat_id = configured_home_channel(getattr(runner, "config", None))
    if not chat_id:
        logger.warning("Hermes WeChat Enhance: no WeChat home channel for startup notification")
        return False

    await adapter.send(chat_id, startup_ready_message(), metadata=weixin_metadata())
    logger.warning("Hermes WeChat Enhance: startup ready notification sent to %s", _redact_chat(chat_id))
    return True


def _redact_chat(chat_id: str) -> str:
    if len(chat_id) <= 8:
        return chat_id
    return f"{chat_id[:4]}...{chat_id[-4:]}"
