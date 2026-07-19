#!/usr/bin/env python3
from __future__ import annotations
import asyncio, importlib, sys, tempfile
from pathlib import Path
from types import SimpleNamespace
GATEWAY_SRC=Path("/opt/hermes")
if str(GATEWAY_SRC) not in sys.path: sys.path.insert(0,str(GATEWAY_SRC))
wx=importlib.import_module("gateway.platforms.weixin"); MessageSendQueue=wx.MessageSendQueue; ReplyBudgetStore=wx.ReplyBudgetStore; WeixinAdapter=wx.WeixinAdapter
def require(c,m):
    if not c: raise SystemExit("FAIL "+m)
def test_queue_contract():
    q=MessageSendQueue(); md={"_delivery_id":"delivery-A","_delivery_chunk_index":0}; require(q.enqueue("acct","chat","hello","chat",None,md) is True,"first enqueue failed"); require(q.enqueue("acct","chat","dupe","chat",None,md) is False,"duplicate enqueue was not suppressed"); require(q.pending_count("acct","chat")==1,"pending mismatch"); item=q.peek("acct","chat"); require(item and item["content"]=="hello","peek failed"); require(q.pending_count("acct","chat")==1,"peek destructive"); q.dequeue("acct","chat"); require(q.pending_count("acct","chat")==0,"dequeue failed"); print("QUEUE_CONTRACT_OK")
def test_budget_contract():
    with tempfile.TemporaryDirectory() as td:
        s=ReplyBudgetStore(td); s.update_token("acct","chat","token-1"); require(s.get_count("acct","chat")==0,"initial count"); require(s.next_count("acct","chat")==1,"next_count"); require(s.get_count("acct","chat")==0,"next committed"); s.commit_count("acct","chat",1); require(s.get_count("acct","chat")==1,"commit failed"); print("BUDGET_CONTRACT_OK")
async def test_drain_success_and_failure():
    with tempfile.TemporaryDirectory() as td:
        a=object.__new__(WeixinAdapter); a.platform=SimpleNamespace(value="weixin"); a._account_id="acct"; a._send_queue=MessageSendQueue(); a._budget_store=ReplyBudgetStore(td); a._budget_store.update_token("acct","chat","token-1"); a._token_store=SimpleNamespace(get=lambda account_id,chat_id:"token-fallback"); a._context_delivery_locks={}; a._send_chunk_delay_seconds=0.0; sent=[]
        async def ok_send(**kw): sent.append(kw); return None
        a._send_text_chunk=ok_send; a._send_queue.enqueue("acct","chat","chunk","chat",None,{"_delivery_id":"D1","_delivery_chunk_index":0,"model_name":"m"}); r=await a._drain_pending("chat"); require(r.success is True,"success returned failure"); require(a._send_queue.pending_count("acct","chat")==0,"success did not dequeue"); require(a._budget_store.get_count("acct","chat")==1,"success no budget"); require(sent and sent[0]["client_id"].startswith("hermes-weixin-"),"client_id not generated")
        sent.clear(); a._send_queue.enqueue("acct","chat","chunk2","chat",None,{"_delivery_id":"D2","_delivery_chunk_index":0,"model_name":"m"}); before=a._budget_store.get_count("acct","chat")
        async def fail_send(**kw): sent.append(kw); raise RuntimeError("simulated reject")
        a._send_text_chunk=fail_send; r=await a._drain_pending("chat"); require(r.success is False,"failure returned success"); require(a._send_queue.pending_count("acct","chat")==1,"failure removed chunk"); require(a._budget_store.get_count("acct","chat")==before,"failure consumed budget"); a._send_queue.enqueue("acct","chat","dupe","chat",None,{"_delivery_id":"D2","_delivery_chunk_index":0,"model_name":"m"}); require(a._send_queue.pending_count("acct","chat")==1,"dedupe failed"); print("DRAIN_CONTRACT_OK"); print("DELIVERY_ID_CONTRACT_OK"); print("SENDRESULT_SEMANTICS_OK")
async def test_rate_limit_retry_success():
    a=object.__new__(WeixinAdapter); a.platform=SimpleNamespace(value="weixin"); a._send_session=object(); a._base_url="https://example.invalid"; a._token="token"; a._send_chunk_retries=2; a._send_chunk_retry_delay_seconds=0.0; a._rate_limit_cooldown_remaining=lambda:0.0; a._record_rate_limit_event=lambda:False; a._reset_rate_limit_circuit=lambda:None; a._token_store=SimpleNamespace(_cache={},_key=lambda account_id,chat_id:f"{account_id}:{chat_id}"); a._account_id="acct"; calls=[]
    async def fake(*args,**kw): calls.append(kw); return {"ret":-2,"errcode":-2,"errmsg":"rate limited"} if len(calls)==1 else {"ret":0}
    old=wx._send_message; wx._send_message=fake
    try: await a._send_text_chunk_locked(chat_id="chat",chunk="hello",context_token="ctx-token",client_id="client-id")
    finally: wx._send_message=old
    require(len(calls)==2,"retry count mismatch"); require(calls[0]["context_token"]=="ctx-token","context token lost"); print("RATE_LIMIT_RETRY_OK"); print("CONTEXT_TOKEN_RETRY_OK")
async def main():
    test_queue_contract(); test_budget_contract(); await test_drain_success_and_failure(); await test_rate_limit_retry_success(); print("RELIABLE_DELIVERY_CONTRACT_OK")
if __name__=="__main__": asyncio.run(main())
