#!/usr/bin/env python3
"""Real Core result producer -> queued-first-response -> actual Weixin bubbles.

Only physical IO is fake. No agent/end hook, no completed wrapper, no response
model metadata; that was the untested 2026-10-16 production path.
"""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from types import MethodType, SimpleNamespace

ROOT=Path(os.environ.get('HERMES_WECHAT_ENHANCE_SOURCE_DIR',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(ROOT))


async def main():
    from gateway.config import PlatformConfig,Platform
    from gateway.session import SessionSource
    from gateway.platforms.weixin import WeixinAdapter
    from gateway.run_turn_runner import TurnRunner
    from gateway.turn_context import TurnContext
    from gateway.run_turn import GatewayTurnMixin
    from gateway.run import GatewayRunner
    from hermes_wechat_enhance import v021_bubble_footer as M
    M.patch_turn_runner_status()
    physical=[]
    def make_adapter(account):
        adapter=WeixinAdapter(PlatformConfig(enabled=True,token='synthetic-token',
            extra={'account_id':account,'send_chunk_delay_seconds':0}))
        adapter._send_session=object()
        async def send(_self,*,chat_id,chunk,context_token,client_id):
            physical.append((account,chat_id,chunk))
        adapter._send_text_chunk=MethodType(send,adapter)
        assert M.patch_adapter(adapter)
        return adapter
    adapter=make_adapter('synthetic-account')
    peer='synthetic-peer'
    source=SessionSource(platform=Platform.WEIXIN,chat_id=peer)
    for model,body in (
            ('synthetic-primary','A queued final response, no stream consumer.'),
            ('synthetic-backup','Another queued final, after a fallback.'),
            ('synthetic-backup','[[as_document]]\nModel text after Core attachment-marker extraction.'),
            ('synthetic-backup','Large final response\n'+('content from actual model result. '*1500))):
        M._TURN_MODELS.clear()
        getattr(M,'_FINAL_ORIGINS',{}).clear()
        M._remember_model(peer,'synthetic-stale-model')
        response=dict(final_response=body,model='synthetic-requested-model',completed=True,failed=False,messages=[])
        ctx=TurnContext(source=source,agent_holder=[SimpleNamespace(model=model)],
            _status_adapter=adapter,result_holder=[None],session_key='synthetic-session',
            stream_consumer_holder=[None],_status_thread_metadata=None,event_message_id=None,
            inbound_message_id='synthetic-inbound',run_generation=1)
        producer=object.__new__(TurnRunner)
        producer._ctx=ctx
        # Actual result producer: it runs BEFORE _run_agent_inner returns or
        # agent:end. Then deliberately replace mutable chat state before send.
        producer._finish_stream_consumer(response,[],None)
        M._remember_model(peer,'synthetic-next-turn')
        before=len(physical)
        owner=object.__new__(GatewayRunner)
        await GatewayTurnMixin._run_agent_deliver_first_response(owner,ctx,adapter,response,response,None)
        chunks=physical[before:]
        assert chunks and all(('`'+model+'`') in chunk for _,_,chunk in chunks),chunks[-1][2][-100:]
        if len(body)>10000: assert len(chunks)>1
        # Control traffic must not inherit model origin, including a matching
        # final body when the producer explicitly marks it as system-owned.
        await adapter.send(peer,'Queued for next turn',metadata={'is_system':True})
        assert '`hermes`' in physical[-1][2]
        await adapter.send(peer,body,metadata={'is_system':True})
        assert all('`hermes`' in row[2] for row in physical[-len(chunks):])
    # Identical peer/body on another account is not the same result producer.
    other=make_adapter('another-synthetic-account')
    M._TURN_MODELS.clear()
    result=await other.send(peer,body)
    assert result.success and '`hermes`' in physical[-1][2]
    # Identical result bytes attributed to two models are ambiguous, not last-wins.
    M._record_final_origin(adapter,peer,'synthetic-other-model',body)
    assert M._resolve_model(peer,body,{},adapter=adapter)[0]=='unknown-model'
    # A model-declared message without its model evidence is not system traffic.
    assert M._resolve_model(peer,'new model text',{'actor':'model'},adapter=adapter)[0]=='unknown-model'
    # Distinct long bodies sharing their first500 characters are not the same
    # response (the previous prefix heuristic could not distinguish them).
    M._FINAL_ORIGINS.clear()
    first,second=('same prefix '*100)+'first',('same prefix '*100)+'second'
    M._record_final_origin(adapter,peer,'model-a',first)
    M._record_final_origin(adapter,peer,'model-b',second)
    assert M._resolve_model(peer,first,{},adapter=adapter)[0]=='model-a'
    assert M._resolve_model(peer,second,{},adapter=adapter)[0]=='model-b'
    for flags in ({'failed':True},{'interrupted':True},{'completed':False}):
        M._FINAL_ORIGINS.clear()
        M._TURN_MODELS.clear()
        producer._finish_stream_consumer(dict(final_response='system diagnostic',messages=[],**flags),[],None)
        assert M._resolve_model(peer,'system diagnostic',{},adapter=adapter)[0]=='hermes'
    print('FINAL_ORIGIN_REAL_PRODUCER_QUEUE_SPLIT_ACCOUNT_OK')


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='enhance-final-origin-') as raw:
        os.environ['HERMES_HOME']=raw
        asyncio.run(main())
