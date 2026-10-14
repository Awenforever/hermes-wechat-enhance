#!/usr/bin/env python3
"""Synthetic transport ledger lifecycle; never reads a real Hermes profile."""
import asyncio
import argparse
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('bubble_test_fixtures', ROOT / 'scripts/test-v021-bubble-footer.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
from hermes_wechat_enhance.v021_bubble_footer import PendingBubbleStore, patch_adapter


async def main(root, adapter_type=fixtures.FakeAdapter):
    os.environ['HERMES_HOME'] = str(root)
    adapter = adapter_type()
    assert patch_adapter(adapter)
    ledger = adapter._hermes_transport_receipts_v1
    binding, other = 'a' * 64, 'b' * 64
    def read(key=binding, chat='peer'):
        return ledger.read_receipts(adapter._account_id, chat, key)
    adapter.fail_next = True
    await adapter.send('peer', 'one', metadata={'_hermes_transport_binding_v1':binding})
    await adapter.send('peer', 'two', metadata={'_hermes_transport_binding_v1':other})
    assert not adapter.sent and ledger.count(adapter._account_id, 'peer') == 2
    assert [r['phase'] for r in read()['records']] == ['queued']
    assert [r['phase'] for r in read(other)['records']] == ['queued']
    # Reopen durable state and drain in a DIFFERENT task with no inherited scope.
    restored = PendingBubbleStore(ledger.path)
    assert restored.peek(adapter._account_id, 'peer')['transport_binding'] == binding
    await asyncio.create_task(adapter._drain_pending('peer'), context=__import__('contextvars').Context())
    assert len(adapter.sent) == 2 and ledger.count(adapter._account_id, 'peer') == 0
    for key in (binding,other):
        page = read(key)
        assert [r['phase'] for r in page['records']] == ['queued','acknowledged']
        assert page['records'][0]['client_reference'] == page['records'][1]['client_reference']
        assert not page['complete_inventory_proven'] and not page['external_delivery_proven']
        assert not page['canonical_quote_mapping_proven']
        assert not read(key, 'wrong-peer')['records']
        assert restored.read_receipts(adapter._account_id, 'peer', key)['records'] == page['records']
    assert adapter.sent[0][1].startswith('one') and adapter.sent[1][1].startswith('two')
    prior = read()['records'][-1]
    ledger.record_acknowledgement(adapter._account_id, 'peer', adapter.sent[0][3], binding)
    assert read()['records'][-1] == prior  # replay keeps the canonical occurrence
    assert not ledger.read_receipts('wrong-account', 'peer', binding)['records']
    assert not ledger.read_receipts(adapter._account_id, 'peer', binding, after_sequence=prior['seq'])['records']
    await adapter.send('peer', 'immediate', metadata={'_hermes_transport_binding_v1':binding})
    assert [r['phase'] for r in read()['records']] == ['queued','acknowledged','acknowledged']
    before = len(adapter.sent)
    try: await adapter.send('peer', 'invalid', metadata={'_hermes_transport_binding_v1':'private-invalid'})
    except ValueError: pass
    else: raise AssertionError('invalid binding reached sender')
    assert len(adapter.sent) == before
    # A storage error after successful network IO does not resend or change result.
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute('DROP TABLE transport_receipts_v1')
    physical = len(adapter.sent)
    result = await adapter.send('peer', 'storage-failure', metadata={'_hermes_transport_binding_v1':binding})
    assert result.success and len(adapter.sent) == physical + 1
    assert ledger.receipts_available is False
    # The same telemetry failure on deferred acknowledgement must not leave an
    # already-sent queue row behind and trigger another physical send.
    adapter.fail_next = True
    await adapter.send('peer', 'deferred-storage-failure', metadata={'_hermes_transport_binding_v1':binding})
    assert ledger.count(adapter._account_id, 'peer') == 1
    physical = len(adapter.sent)
    result = await adapter._drain_pending('peer')
    assert result['ok'] and len(adapter.sent) == physical + 1
    assert ledger.count(adapter._account_id, 'peer') == 0
    await adapter._drain_pending('peer')
    assert len(adapter.sent) == physical + 1
    assert not adapter._hermes_wechat_v021_retry_tasks


def legacy_migration(root):
    path = root / 'legacy.sqlite3'
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('CREATE TABLE pending_bubbles(seq INTEGER PRIMARY KEY AUTOINCREMENT, account_key TEXT NOT NULL, chat_key TEXT NOT NULL,client_id TEXT NOT NULL UNIQUE,chunk TEXT NOT NULL,model TEXT NOT NULL,enqueued_at REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT "")')
        keys = PendingBubbleStore._keys('old-account','old-peer')
        connection.execute('INSERT INTO pending_bubbles(account_key,chat_key,client_id,chunk,model,enqueued_at) VALUES(?,?,?,?,?,?)', (*keys,'old-id','retained body','old-model',1.0))
    migrated = PendingBubbleStore(path)
    row = migrated.peek('old-account','old-peer')
    assert row['chunk'] == 'retained body' and row['transport_binding'] is None
    assert not migrated.read_receipts('old-account','old-peer','a'*64)['records']
    assert PendingBubbleStore(path).peek('old-account','old-peer') == row


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--hermes-root', type=Path)
    args = parser.parse_args()
    adapter_type = fixtures.FakeAdapter
    if args.hermes_root:
        sys.path.insert(0, str(args.hermes_root.resolve()))
        from gateway.config import PlatformConfig
        from gateway.platforms.weixin import WeixinAdapter
        class NativeAdapter(WeixinAdapter):
            def __init__(self):
                super().__init__(PlatformConfig(enabled=True, token='synthetic-token', extra={
                    'account_id':'synthetic-account','send_chunk_delay_seconds':0}))
                self._send_session = object()
                self._token_store = fixtures.Tokens()
                self.sent, self.fail_next, self.cooldown_failures = [], False, 0
            async def _send_text_chunk(self, **kwargs):
                await fixtures.FakeAdapter._send_text_chunk(self, **kwargs)
        adapter_type = NativeAdapter
    with tempfile.TemporaryDirectory(prefix='enhance-receipt-') as folder:
        root = Path(folder)
        legacy_migration(root)
        asyncio.run(main(root, adapter_type))
    print('TRANSPORT_RECEIPT_PUBLISHER_TEST_OK')
