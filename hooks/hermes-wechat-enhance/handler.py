# WECHAT_ENHANCE_IMPORT_BOOTSTRAP_V1
import sys
from pathlib import Path
_SKILL_DIR = Path("/opt/data/skills/hermes-wechat-enhance")
if str(_SKILL_DIR) not in sys.path: sys.path.insert(0, str(_SKILL_DIR))
from hermes_wechat_enhance.store import MessageStore
_store = MessageStore()
async def handle(event_type, context):
    # WECHAT_ENHANCE_STARTUP_READY_OWNER_V1
    if event_type == "gateway:startup": await _send_startup_ready(context); return
    if event_type == "agent:start": _store.append_inbound(context)
    elif event_type == "agent:end": _store.append_outbound(context)
    return None
# WECHAT_ENHANCE_STARTUP_READY_OWNER_V1
# WECHAT_ENHANCE_STARTUP_READY_ACK_V2
async def _send_startup_ready(context: dict):
    import logging, os
    log=globals().get("logger") or logging.getLogger(__name__); ready=os.getenv("HERMES_WEIXIN_STARTUP_READY_NOTIFY", "").strip()
    if not ready or ready == "1": ready = "♻️ Gateway online — Hermes is back and ready."
    if ready.lower() in {"0","false","no","off","disabled"}: log.warning("Hermes WeChat Enhance: startup ready notification disabled"); return
    weixin_chat_id=os.getenv("HERMES_PROACTIVE_WEIXIN_CHAT_ID", "").strip()
    if not weixin_chat_id: log.warning("Hermes WeChat Enhance: no HERMES_PROACTIVE_WEIXIN_CHAT_ID; skip startup ready"); return
    adapters=context.get("adapters") if isinstance(context,dict) else None
    if not adapters:
        runner=None
        try:
            from gateway.run import _gateway_runner_ref
            runner=_gateway_runner_ref()
        except Exception as exc: log.warning("Hermes WeChat Enhance: gateway runner lookup failed: %s", exc)
        adapters=getattr(runner,"adapters",None) if runner is not None else None
    if not adapters: log.warning("Hermes WeChat Enhance: no adapters available for startup ready"); return
    for key,adapter in adapters.items():
        key_value=getattr(key,"value",key)
        if key_value == "weixin":
            result=await adapter.send(weixin_chat_id, ready, metadata={"is_system":True,"model_name":"hermes","model":"hermes","resolved_model":"hermes","routed_model":"hermes","source":"wechat-enhance-startup-ready","_delivery_id":"hermes-wechat-enhance-startup-ready"})
            if getattr(result,"success",False): log.warning("Hermes WeChat Enhance: startup ready notification sent to %s (delivery confirmed)", weixin_chat_id)
            else: log.warning("Hermes WeChat Enhance: startup ready not delivered to %s: %s", weixin_chat_id, getattr(result,"error","unknown"))
            return
    log.warning("Hermes WeChat Enhance: weixin adapter not found for startup ready")
