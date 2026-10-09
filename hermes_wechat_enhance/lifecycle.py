"""Weixin lifecycle-notification ownership for current Hermes.

Hermes Core uses one ``gateway_restart_notification`` switch for both shutdown
and startup.  Turning it off to hide a duplicate ready message also silences the
shutdown half, which violates the operator's state-continuity contract.  The
plugin therefore suppresses only Core's two startup send methods at runtime and
leaves shutdown notifications and the user's persisted Core configuration
untouched.
"""

from __future__ import annotations

import functools
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


_HOOK_LOADED_AT_NS = time.time_ns()


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def boot_identity() -> str:
    """Stable for this hook import, different for the next gateway process."""
    return f"{os.getpid()}:{_HOOK_LOADED_AT_NS}"


def _receipt_path() -> Path:
    return _home() / "plugin-data" / "hermes-wechat-enhance" / "startup-ready-receipt.json"


def startup_already_accepted(identity: str) -> bool:
    try:
        value = json.loads(_receipt_path().read_text(encoding="utf-8"))
        return value.get("boot_identity") == identity and value.get("accepted") is True
    except Exception:
        return False


def record_startup_accepted(identity: str, *, queued: bool) -> None:
    path = _receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {
                "boot_identity": identity,
                "accepted": True,
                "queued": bool(queued),
                "recorded_at": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _weixin_platform_configs(runner: Any) -> list[Any]:
    configs: list[Any] = []
    seen: set[int] = set()
    candidates = [getattr(runner, "config", None)]
    candidates.extend((getattr(runner, "_profile_configs", None) or {}).values())
    for config in candidates:
        platforms = getattr(config, "platforms", None)
        if not isinstance(platforms, dict):
            continue
        for key, value in platforms.items():
            name = str(getattr(key, "value", key) or "").lower()
            if name == "weixin" and id(value) not in seen:
                seen.add(id(value))
                configs.append(value)
    return configs


@contextmanager
def _core_startup_suppressed(runner: Any) -> Iterator[None]:
    """Temporarily mute only while a Core startup method is executing."""
    configs = _weixin_platform_configs(runner)
    prior = [(config, getattr(config, "gateway_restart_notification", True)) for config in configs]
    for config, _value in prior:
        config.gateway_restart_notification = False
    try:
        yield
    finally:
        for config, value in prior:
            config.gateway_restart_notification = value


def patch_core_weixin_startup_notifications(runner: Any) -> bool:
    """Make wechat-enhance the sole Weixin *startup* notice owner.

    Core remains responsible for shutdown notices.  Other platforms retain
    their native startup behavior, and no config file is changed.
    """
    if runner is None or getattr(runner, "_hermes_wechat_startup_owner_v1", False):
        return False
    installed = False
    for name in ("_send_restart_notification", "_send_home_channel_startup_notifications"):
        original = getattr(runner, name, None)
        if not callable(original):
            continue

        @functools.wraps(original)
        async def wrapped(*args: Any, __original=original, **kwargs: Any) -> Any:
            with _core_startup_suppressed(runner):
                return await __original(*args, **kwargs)

        setattr(runner, name, wrapped)
        installed = True
    if installed:
        runner._hermes_wechat_startup_owner_v1 = True
    return installed
