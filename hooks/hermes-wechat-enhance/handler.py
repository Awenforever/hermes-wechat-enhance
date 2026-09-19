# WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V1
# WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V2
# HERMES_WECHAT_SLASH_COMMAND_DEDUP_HOOK_V1
# HERMES_WECHAT_CURRENT_OFFICIAL_RUNTIME_COMPAT_HOOK_V1
import os
import sys
from pathlib import Path


def _resolve_skill_dir() -> Path:
    explicit = os.getenv(
        "HERMES_WECHAT_ENHANCE_SOURCE_DIR",
        "",
    ).strip()
    if explicit:
        return Path(explicit).expanduser()

    skills_root = os.getenv("HERMES_SKILLS_DIR", "").strip()
    if skills_root:
        return Path(skills_root).expanduser() / "hermes-wechat-enhance"

    hermes_home = os.getenv("HERMES_HOME", "").strip()
    if hermes_home:
        home = Path(hermes_home).expanduser()
        plugin = home / "plugins" / "hermes-wechat-enhance"
        if plugin.exists():
            return plugin
        skill = home / "skills" / "hermes-wechat-enhance"
        if skill.exists():
            return skill

    try:
        hook_home = Path(__file__).resolve().parents[2]
        derived = hook_home / "skills" / "hermes-wechat-enhance"
        if derived.exists():
            return derived
    except IndexError:
        pass

    return Path.home() / ".hermes" / "plugins" / "hermes-wechat-enhance"


_SKILL_DIR = _resolve_skill_dir().resolve()
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from hermes_wechat_enhance.current_official_runtime_compat import install_weixin_runtime_compat_hook
from hermes_wechat_enhance.store import MessageStore
from hermes_wechat_enhance.v021_bubble_footer import (
    install_v021_bubble_footer_hook,
    register_turn_model,
)

_store = MessageStore()


async def handle(event_type, context):
    # WECHAT_ENHANCE_STARTUP_READY_OWNER_V1
    if event_type == "gateway:startup":
        legacy_compat = os.getenv("HERMES_WECHAT_ENABLE_LEGACY_RUNTIME_COMPAT", "").strip().lower()
        if legacy_compat in {"1", "true", "yes", "on"}:
            await install_weixin_runtime_compat_hook(context)
        else:
            await install_v021_bubble_footer_hook(context)
        await _send_startup_ready(context)
        return
    if event_type == "agent:start":
        if _audit_enabled():
            _store.append_inbound(context)
    elif event_type == "agent:end":
        register_turn_model(context)
        if _audit_enabled():
            _store.append_outbound(context)
    return None


def _audit_enabled() -> bool:
    value = os.getenv("HERMES_WECHAT_CAPTURE_MESSAGES", "1").strip().lower()
    return value not in {"0", "false", "no", "off", "disabled"}


# WECHAT_ENHANCE_STARTUP_READY_OWNER_V1
# WECHAT_ENHANCE_STARTUP_READY_ACK_V2
# WECHAT_ENHANCE_STARTUP_READY_SUPPRESS_ONCE_V1
async def _send_startup_ready(context: dict):
    import logging

    log = globals().get("logger") or logging.getLogger(__name__)

    # A controlled deployment restart can create this one-shot sentinel to
    # prevent an unsolicited real WeChat notification.  Normal later restarts
    # preserve the existing startup-ready behavior.
    hermes_home = Path(
        os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
    ).expanduser()
    suppress_once = hermes_home / ".hermes" / "wechat-enhance" / "suppress-startup-ready-once"
    if suppress_once.exists():
        try:
            suppress_once.unlink()
        except OSError as exc:
            log.warning("Hermes WeChat Enhance: failed to consume startup-ready suppress sentinel: %s", exc)
        log.warning("Hermes WeChat Enhance: startup ready notification suppressed once for controlled deployment")
        return

    ready = os.getenv("HERMES_WEIXIN_STARTUP_READY_NOTIFY", "").strip()
    if not ready:
        log.info("Hermes WeChat Enhance: startup ready notification not configured")
        return
    if ready == "1":
        ready = "♻️ Gateway online — Hermes is back and ready."
    if ready.lower() in {"0", "false", "no", "off", "disabled"}:
        log.warning("Hermes WeChat Enhance: startup ready notification disabled")
        return
    weixin_chat_id = os.getenv("HERMES_PROACTIVE_WEIXIN_CHAT_ID", "").strip()
    if not weixin_chat_id:
        log.warning("Hermes WeChat Enhance: no HERMES_PROACTIVE_WEIXIN_CHAT_ID; skip startup ready")
        return
    adapters = context.get("adapters") if isinstance(context, dict) else None
    if not adapters:
        runner = None
        try:
            from gateway.run import _gateway_runner_ref

            runner = _gateway_runner_ref()
        except Exception as exc:
            log.warning("Hermes WeChat Enhance: gateway runner lookup failed: %s", exc)
        adapters = getattr(runner, "adapters", None) if runner is not None else None
    if not adapters:
        log.warning("Hermes WeChat Enhance: no adapters available for startup ready")
        return
    for key, adapter in adapters.items():
        key_value = getattr(key, "value", key)
        if key_value == "weixin":
            result = await adapter.send(
                weixin_chat_id,
                ready,
                metadata={
                    "is_system": True,
                    "model_name": "hermes",
                    "model": "hermes",
                    "resolved_model": "hermes",
                    "routed_model": "hermes",
                    "source": "wechat-enhance-startup-ready",
                    "_delivery_id": "hermes-wechat-enhance-startup-ready",
                },
            )
            if getattr(result, "success", False):
                log.warning(
                    "Hermes WeChat Enhance: startup ready notification sent to %s (delivery confirmed)",
                    weixin_chat_id,
                )
            else:
                log.warning(
                    "Hermes WeChat Enhance: startup ready not delivered to %s: %s",
                    weixin_chat_id,
                    getattr(result, "error", "unknown"),
                )
            return
    log.warning("Hermes WeChat Enhance: weixin adapter not found for startup ready")
