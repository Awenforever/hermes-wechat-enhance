"""Profile-scoped settings shared by the hook and operator surfaces."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PLUGIN_ID = "hermes-wechat-enhance"
_FALSE = {"0", "false", "no", "off", "disabled"}
_TRUE = {"1", "true", "yes", "on", "enabled"}


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def _load_config() -> Mapping[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        value = load_config_readonly() or {}
        return value if isinstance(value, Mapping) else {}
    except Exception:
        try:
            import yaml

            value = yaml.safe_load((_hermes_home() / "config.yaml").read_text(encoding="utf-8")) or {}
            return value if isinstance(value, Mapping) else {}
        except Exception:
            return {}


def plugin_setting(key: str, default: Any = None) -> Any:
    """Read the current Hermes plugin setting, preferring the modern settings tree."""
    config = _load_config()
    plugins = config.get("plugins") if isinstance(config, Mapping) else None
    entries = plugins.get("entries") if isinstance(plugins, Mapping) else None
    entry = entries.get(PLUGIN_ID) if isinstance(entries, Mapping) else None
    if not isinstance(entry, Mapping):
        return default
    for namespace in ("settings", "config"):
        values = entry.get(namespace)
        if isinstance(values, Mapping) and key in values:
            return values[key]
    return default


def configured_bool(env_name: str, setting_name: str, default: bool) -> bool:
    """Resolve env override, then Hermes plugin config, then the public default."""
    raw_env = os.environ.get(env_name)
    if raw_env is not None and raw_env.strip():
        normalized = raw_env.strip().lower()
        if normalized in _FALSE:
            return False
        if normalized in _TRUE:
            return True
    value = plugin_setting(setting_name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _FALSE:
            return False
        if normalized in _TRUE:
            return True
    return bool(default)


def startup_ready_message(default_message: str) -> str | None:
    """Return the configured ready message, or ``None`` when explicitly disabled."""
    raw_env = os.environ.get("HERMES_WEIXIN_STARTUP_READY_NOTIFY")
    if raw_env is not None and raw_env.strip():
        value = raw_env.strip()
        normalized = value.lower()
        if normalized in _FALSE:
            return None
        if normalized in _TRUE:
            return default_message
        return value
    if not configured_bool(
        "HERMES_WEIXIN_STARTUP_READY_NOTIFY",
        "startup_notification",
        True,
    ):
        return None
    message = plugin_setting("startup_message", default_message)
    return str(message).strip() or default_message

