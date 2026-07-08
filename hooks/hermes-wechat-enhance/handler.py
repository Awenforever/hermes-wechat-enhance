from hermes_wechat_enhance.store import MessageStore
from hermes_wechat_enhance.startup_ready import send_startup_ready_notification

_store = MessageStore()


async def handle(event_type, context):
    if event_type == "gateway:startup":
        await send_startup_ready_notification(context if isinstance(context, dict) else {})
    elif event_type == "agent:start":
        _store.append_inbound(context)
    elif event_type == "agent:end":
        _store.append_outbound(context)
    return None
