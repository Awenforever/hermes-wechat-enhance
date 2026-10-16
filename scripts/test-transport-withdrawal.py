#!/usr/bin/env python3
"""Scoped FIFO withdrawal, including the real asynchronous drain lock."""
import asyncio
import argparse
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import MethodType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec = importlib.util.spec_from_file_location('withdraw_fixtures',ROOT/'scripts/test-v021-bubble-footer.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
from hermes_wechat_enhance.v021_bubble_footer import PendingBubbleStore,patch_adapter


async def test(root,inflight=False,core=None):
    os.environ['HERMES_HOME'] = str(root)
    adapter = fixtures.FakeAdapter()
    if core:
        from gateway.config import PlatformConfig
        from gateway.platforms.weixin import WeixinAdapter
        class NativeAdapter(WeixinAdapter):
            def __init__(self):
                super().__init__(PlatformConfig(enabled=True,token='synthetic-token',extra={
                    'account_id':'synthetic-account','send_chunk_delay_seconds':0}))
                self._send_session = object()
                self._token_store = fixtures.Tokens()
                self.sent,self.fail_next,self.cooldown_failures = [],False,0
            async def _send_text_chunk(self,**kwargs):
                await fixtures.FakeAdapter._send_text_chunk(self,**kwargs)
        adapter = NativeAdapter()
    entered,release = asyncio.Event(),asyncio.Event()
    original = adapter._send_text_chunk
    gated_client = None
    async def gated(self,**kwargs):
        if inflight and not self.fail_next and kwargs['client_id']==gated_client:
            entered.set()
            await release.wait()
        return await original(**kwargs)
    adapter._send_text_chunk = MethodType(gated,adapter)
    assert patch_adapter(adapter)
    queue = adapter._hermes_transport_receipts_v1
    a,b = 'a'*64,'b'*64
    adapter.fail_next = True
    for body,binding in (('A1',a),('B',b),('A2',a)):
        assert (await adapter.send('peer',body,metadata={'_hermes_transport_binding_v1':binding})).success
    gated_client = queue.peek(adapter._account_id,'peer')['client_id']
    if inflight:
        draining = asyncio.create_task(adapter._drain_pending('peer'))
        await entered.wait()
        cancelling = asyncio.create_task(adapter._hermes_transport_withdraw_binding_v1('peer',a))
        # Durable storage is offloaded; a scheduler yield is not proof that its
        # transaction committed. Wait for the explicit durable observation.
        deadline = asyncio.get_running_loop().time() + 3
        while not queue.withdrawal_requested(adapter._account_id,'peer',a):
            if cancelling.done():
                await cancelling
                raise AssertionError('withdrawal finished without durable deny')
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.001)
        assert queue.withdrawal_requested(adapter._account_id,'peer',a)
        release.set()
        await draining
        result = await cancelling
        assert [s[1].split('\n\n---')[0] for s in adapter.sent] == ['A1','B']
        assert [r['phase'] for r in queue.read_receipts(adapter._account_id,'peer',a)['records']] == ['queued','queued','acknowledged','withdrawn']
    else:
        result = await adapter._hermes_transport_withdraw_binding_v1('peer',a)
        assert result['removed_count']==2 and not adapter.sent
        assert queue.count(adapter._account_id,'peer')==1
        assert PendingBubbleStore(queue.path).withdrawal_requested(adapter._account_id,'peer',a)
        assert not queue.withdrawal_requested(adapter._account_id,'other',a)
        assert not queue.withdrawal_requested('other-account','peer',a)
        assert (await adapter.send('peer','A3',metadata={'_hermes_transport_binding_v1':a})).success
        assert queue.count(adapter._account_id,'peer')==1 and not adapter.sent
        await adapter._drain_pending('peer')
        assert [s[1].split('\n\n---')[0] for s in adapter.sent] == ['B']
    assert result['already_sent_possible'] and not result['external_recall_proven']
    assert (await adapter._hermes_transport_withdraw_binding_v1('peer',a))['removed_count']==0
    assert queue.count(adapter._account_id,'peer')==0
    tasks = list(adapter._hermes_wechat_v021_retry_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert not adapter._hermes_wechat_v021_retry_tasks


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--hermes-root',type=Path)
    args = parser.parse_args()
    if args.hermes_root: sys.path.insert(0,str(args.hermes_root.resolve()))
    with tempfile.TemporaryDirectory(prefix='enhance-withdraw-') as folder:
        asyncio.run(test(Path(folder)/'pending',core=args.hermes_root))
        asyncio.run(test(Path(folder)/'inflight',True,args.hermes_root))
    print('TRANSPORT_WITHDRAWAL_TEST_OK')
