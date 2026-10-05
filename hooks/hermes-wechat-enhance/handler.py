# WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V1
# WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V2
# HERMES_WECHAT_SLASH_COMMAND_DEDUP_HOOK_V1
# HERMES_WECHAT_CURRENT_OFFICIAL_RUNTIME_COMPAT_HOOK_V1
import os
import sys
import json
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
from hermes_wechat_enhance.peer import resolve_weixin_peer
from hermes_wechat_enhance.settings import configured_bool, startup_ready_message
from hermes_wechat_enhance.store import MessageStore
from hermes_wechat_enhance.v021_bubble_footer import (
    install_v021_bubble_footer_hook,
    register_turn_model,
    refresh_runtime_status,
)

_store = MessageStore()


async def handle(event_type, context):
    # WECHAT_ENHANCE_STARTUP_READY_OWNER_V1
    if event_type == "gateway:startup":
        if configured_bool(
            "HERMES_WECHAT_ENABLE_LEGACY_RUNTIME_COMPAT",
            "legacy_runtime_compat",
            False,
        ):
            await install_weixin_runtime_compat_hook(context)
        else:
            await install_v021_bubble_footer_hook(context)
        await _send_startup_ready(context)
        refresh_runtime_status(context)
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
    return configured_bool("HERMES_WECHAT_CAPTURE_MESSAGES", "capture_messages", True)


# WECHAT_ENHANCE_STARTUP_READY_OWNER_V1
# WECHAT_ENHANCE_STARTUP_READY_ACK_V2
# WECHAT_ENHANCE_STARTUP_READY_SUPPRESS_ONCE_V2
def _consume_startup_suppression(hermes_home: Path, log) -> bool:
    """Consume one deployment sentinel without allowing an undeletable file to suppress forever."""
    candidates = (
        hermes_home / "wechat-enhance" / "suppress-startup-ready-once",
        # 2.1.7 and earlier accidentally inserted an extra .hermes segment.
        hermes_home / ".hermes" / "wechat-enhance" / "suppress-startup-ready-once",
    )
    sentinel = next((path for path in candidates if path.exists()), None)
    if sentinel is None:
        return False
    receipt = (
        hermes_home
        / "plugin-data"
        / "hermes-wechat-enhance"
        / "startup-suppression-consumed.json"
    )
    try:
        stat = sentinel.stat()
        identity = {"path": str(sentinel), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
    except OSError:
        identity = {"path": str(sentinel)}
    try:
        previous = json.loads(receipt.read_text(encoding="utf-8"))
    except Exception:
        previous = None
    if previous == identity:
        log.warning(
            "Hermes WeChat Enhance: ignoring already-consumed undeletable startup suppression sentinel"
        )
        return False
    failed = []
    for path in candidates:
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError as exc:
            failed.append((path, exc))
    if failed:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        temporary = receipt.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(identity, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, receipt)
        for path, exc in failed:
            log.warning(
                "Hermes WeChat Enhance: startup suppression sentinel could not be deleted; "
                "recorded as consumed path=%s error=%s",
                path,
                exc,
            )
    else:
        try:
            receipt.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Hermes WeChat Enhance: stale suppression receipt cleanup failed: %s", exc)
    return True


async def _send_startup_ready(context: dict):
    import logging

    log = globals().get("logger") or logging.getLogger(__name__)

    # A controlled deployment restart can create this one-shot sentinel to
    # prevent an unsolicited real WeChat notification.  Normal later restarts
    # preserve the existing startup-ready behavior.
    hermes_home = Path(
        os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
    ).expanduser()
    if _consume_startup_suppression(hermes_home, log):
        log.warning("Hermes WeChat Enhance: startup ready notification suppressed once for controlled deployment")
        return

    ready = startup_ready_message("♻️ Gateway online — Hermes is back and ready.")
    if ready is None:
        log.warning("Hermes WeChat Enhance: startup ready notification disabled")
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
            # HERMES_WECHAT_STARTUP_TARGET_INHERIT_V1
            weixin_chat_id, resolution = resolve_weixin_peer(
                os.getenv("HERMES_PROACTIVE_WEIXIN_CHAT_ID", "").strip(),
                account_id=str(getattr(adapter, "_account_id", "") or ""),
            )
            if not weixin_chat_id:
                log.warning(
                    "Hermes WeChat Enhance: startup ready target unavailable (%s); skip",
                    resolution,
                )
                return
            pending_before = 0
            queue = getattr(adapter, "_hermes_wechat_v021_pending_queue", None)
            if queue is not None:
                try:
                    pending_before = int(queue.count(str(getattr(adapter, "_account_id", "")), weixin_chat_id))
                except Exception:
                    pending_before = 0
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
            pending_after = pending_before
            if queue is not None:
                try:
                    pending_after = int(queue.count(str(getattr(adapter, "_account_id", "")), weixin_chat_id))
                except Exception:
                    pending_after = pending_before
            if getattr(result, "success", False):
                if pending_after > 0:
                    log.warning(
                        "Hermes WeChat Enhance: startup ready notification queued "
                        "(pending=%d; awaits fresh Context Token; target=%s)",
                        pending_after,
                        resolution,
                    )
                else:
                    log.warning(
                        "Hermes WeChat Enhance: startup ready notification sent "
                        "(delivery confirmed; target=%s)",
                        resolution,
                    )
            else:
                log.warning(
                    "Hermes WeChat Enhance: startup ready not delivered to %s: %s",
                    weixin_chat_id,
                    getattr(result, "error", "unknown"),
                )
            return
    log.warning("Hermes WeChat Enhance: weixin adapter not found for startup ready")
