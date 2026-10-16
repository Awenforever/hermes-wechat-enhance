#!/usr/bin/env python3
"""Durable restart recovery: real queue/worker, fake physical sender, no inbound."""
import asyncio
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('restart_fixtures', ROOT/'scripts/test-v021-bubble-footer.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
from hermes_wechat_enhance import v021_bubble_footer as M


async def close_tasks(adapter):
    tasks = list(adapter._hermes_wechat_v021_retry_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def main(raw):
    os.environ['HERMES_HOME'] = raw
    M.DRAIN_PROBE_DELAY_SECONDS = 0.005
    first = fixtures.FakeAdapter()
    assert M.patch_adapter(first)
    first.fail_next = True
    await first.send('synthetic-group', 'one')
    await first.send('synthetic-group', 'two')
    await close_tasks(first)
    assert first._hermes_wechat_v021_pending_queue.count(first._account_id, 'synthetic-group') == 2
    restored = fixtures.FakeAdapter()
    assert M.patch_adapter(restored)
    recovery = await restored._hermes_wechat_recover_pending()
    assert recovery == {'scheduled_routes': 1, 'unresolved_routes': 0}
    # No _process_message, /continue, send or token mutation on restored adapter.
    deadline = asyncio.get_running_loop().time() + 3
    while restored._hermes_wechat_v021_retry_tasks:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.001)
    assert len(restored.sent) == 2
    assert restored.sent[0][1].startswith('one') and restored.sent[1][1].startswith('two')
    assert not restored.routed
    queue = restored._hermes_wechat_v021_pending_queue
    queue.enqueue('other-account', 'other-peer', 'other', 'private', 'system')
    assert queue.recover_routes(restored._account_id) == ([], 0)
    # Simulate pre-route-schema backlog; only exact trusted candidates migrate.
    queue.enqueue(restored._account_id, 'legacy-peer', 'legacy', 'preserved', 'model')
    with closing(sqlite3.connect(queue.path)) as connection, connection:
        connection.execute('DELETE FROM pending_routes_v1')
    assert queue.recover_routes(restored._account_id, ('wrong-peer',)) == ([], 1)
    assert queue.recover_routes(restored._account_id, ('legacy-peer',)) == (['legacy-peer'], 0)
    assert queue.count(restored._account_id, 'legacy-peer') == 1
    assert queue.count('other-account', 'other-peer') == 1


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='enhance-restart-drain-') as raw:
        asyncio.run(main(raw))
    print('RESTART_NO_INBOUND_DRAIN_OK')
