# Transport receipt publisher — development contract

2026-10-14. Experimental development branch only; not deployed or released.

Alive must not own Weixin FIFO, tokens or transport retry. A direct outer-method
observer cannot distinguish queue acceptance from successful physical IO, and
deferred drain bypasses it. This publisher is owned by wechat-enhance and does
not depend on Alive being installed.

An explicitly supplied `_hermes_transport_binding_v1` is an opaque 64-lowercase-
hex correlation token, not authority, a model tag or a user identity. Invalid
bindings are refused before calling the adapter. Scope is bound to the exact
asyncio task, adapter instance and chat during submission; child-task inheritance
does not itself grant correlation. Persist the binding with each queued entry so
drain after process restart does not depend on an inherited caller task.

The existing queue store exposes `_hermes_transport_receipts_v1.read_receipts`.
Reads are scoped by account/chat/binding, paginated by sequence. Records contain
only opaque stable occurrence/client references, phase and observation time;
never body, token, raw client/account/chat identifiers or error text. Phases:

- `queued`: this exact entry was accepted in the FIFO transaction.
- `acknowledged`: the captured original physical chunk method returned normally.

Immediate and deferred acknowledgements use the same occurrence scheme. Duplicate
publication retains the original record. Queued acknowledgement and row deletion
share a SQLite transaction. Metadata statement failure is fail-open: sending and
queue deletion proceed, availability is marked false; telemetry never initiates a
retry. Unbound pre-existing queued rows migrate without invented correlation or
historical receipts. Ordinary unbound immediate sends do not open telemetry writes.

The available flag covers only the current store object's write health, not all
historical loss. Storage readers may raise when the ledger is unavailable; a
consumer must treat that as missing evidence, never zero effects. Retention is
bounded to seven days / 10,000 records, and reads always explicitly deny complete
inventory, external user delivery and canonical quote mapping. This is not an
exactly-once transport or an eternal delivery history.

The ledger now has a persistent random epoch and a SQLite AUTOINCREMENT high-water
sequence. Read pages obtain epoch/high-water/records in one read transaction.
Reopen preserves the epoch; a newly created database gets another. Consumers must
reject an unexpected epoch, a high-water mark below their saved cursor or a row
beyond the declared high-water mark. This detects reconstruction/observable
rollback, not every coordinated backup restore or malicious SQLite modification.
Producer upgrades and paired consumer-data migration still need explicit
qualification before production activation; do not silently reset consumer cursors.

Experimental `_hermes_transport_withdraw_binding_v1(chat_id,binding)` accepts only
a trusted-host request; it does not itself authenticate the user. It persists a
route-scoped deny before waiting for the physical-send lock. Pending matching rows
are removed by the host, while unrelated rows retain FIFO order. The drain checks
the deny between physical sends, so one already in-flight chunk may finish but
later matching chunks are suppressed. Future submissions under that same binding
are also suppressed after reopen. `withdrawn` is a local queue/suppression phase,
not remote recall or user feedback. Reported removal count covers only that call's
cleanup, not all removals by the drain. Durable denies are bounded at 10,000 and
never automatically evicted; reaching the cap refuses a new request. Their secure
retention/erasure, controlled upgrade, write failure and background lifetime still
need qualification. No production pause handler is automatically registered.

Critical limitations: a crash after physical IO before the local acknowledgement
transaction remains ambiguous under the existing queue's retry behavior. Client
references are not server-assigned quote IDs. There is no submission-complete,
expiry, interruption or full-inventory signal yet, no consumer authentication/
integrity proof and no Alive result ingestion. Do not promote these records into
canonical delivery or learning outcomes, or remove Alive's direct-observer guard.
Next add qualified publisher/source identity, bounded consumer reconciliation and
explicit ambiguous/finality coverage, then end-to-end autonomous feedback and
longitudinal verification. Enhance final release/acceptance remains after Alive.

Evidence: Windows fake transport tests cover migration/reopen, two distinct
bindings sharing one FIFO, cross-task drain, route isolation, pagination, replay,
immediate acknowledgement, invalid input and write failure. Linux repeats this
with actual stock Weixin constructor/send and only physical IO faked, exact file
overlays, no network and an auto-removed resource-limited container. Existing
bubble counter/model/context-token/FIFO/retry tests pass. These are not fresh
installation, real channel delivery, concurrency/performance or production proof.
