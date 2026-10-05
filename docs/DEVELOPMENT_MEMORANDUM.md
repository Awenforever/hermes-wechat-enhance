# Hermes WeChat Enhance — Development Memorandum

Internal engineering memorandum. Keep incident history, attribution rules,
compatibility traps, and regression obligations here rather than turning the
public README into a development log.

## Non-negotiable invariants

1. **Attribute the physical bubble, not the chat.** Model identity comes from
   the exact producing turn/send rail. Never borrow the last model seen in a
   chat as a default.
2. **Unknown origin fails closed to `hermes`.** Approvals, progress, command
   confirmations, errors, and lifecycle notices must not inherit a model.
3. **Every model rail carries provenance.** Commentary, streamed segments,
   pre-approval/pre-clarification prose, final responses, multipart chunks,
   retry/FIFO recovery, and provider fallback retain the actual model.
4. **A scope ends where its rail ends.** A task-local ContextVar may bridge a
   structurally bounded core call. Chat-global or time-window inference is
   forbidden.
5. **Count only acknowledged physical sends.** Failed delivery and retry do not
   consume or duplicate a number.
6. **FIFO is absolute.** New replies cannot jump pending bubbles. Queue rows
   persist model identity across restart.
7. **Every inbound message refreshes Context Token state.** `/continue` is a
   silent local control path, not the exclusive refresh mechanism.
8. **Fresh slash commands are not content duplicates.** Preserve provider
   message-ID replay protection while bypassing only the secondary text hash.
9. **Transport never inserts display-width newlines.** Markdown source lines,
   links, lists, and code remain semantic; the client owns visual wrapping.
10. **Install and upgrade preserve user state.** Pairing, credentials, queues,
    counters, audit, configuration, Git state, and unrelated files survive.

## Model attribution matrix

| Outbound rail | Required footer | Proof source |
|---|---|---|
| Streamed model commentary | actual model | stream consumer metadata from the resolved turn |
| Model prose before approval/clarification | actual model | task-local boundary provenance |
| Final model answer | actual/fallback model | `agent:end` and response-signature match |
| Multipart model response | actual model on every chunk | one send scope copied into each physical send |
| Pending/retried model bubble | original actual model | model stored with durable FIFO row |
| Plugin business message with model metadata | explicit actual model | sender-owned metadata |
| Approval/clarification prompt or control | `hermes` | explicit system or no model provenance |
| Command acknowledgement, heartbeat, error | `hermes` | explicit system or no model provenance |
| Startup/shutdown/lifecycle notification | `hermes` | explicit system metadata |
| Unknown or unmarked send | `hermes` | fail-closed default |

## Repeated incident record

### Only the final chunk showed the right model

Attribution was attached too late or only to the final result. Capture the
resolved model before creating the stream consumer, and retain one scoped
origin across every physical split chunk.

### Everything showed `deepseek-flash`

A chat-wide current/last-model heuristic leaked into Hermes-owned messages.
Unmarked output must be `hermes`; only structurally proven model rails override
the default.

### Pre-confirmation prose showed `hermes`

Hermes v0.21 `_finalize_boundary_stream()` falls back to
`adapter.send(chat_id, finalize_text)` without consumer metadata. Scope the
consumer's proven model around this exact method. Do not classify text, and do
not extend the scope to the prompt that follows.

Stable runtime marker: `_hermes_wechat_boundary_origin_v2`.

### Tool-era commentary and the normal final send showed `hermes`

The 2026-10-03 production transcript exposed two distinct metadata gaps in one
turn. On non-editable Weixin, Hermes can route model-authored interim commentary
through `TurnRunner._send_status_text` when no stream consumer can be created.
The same helper also sends real system status, so its exact semantic callback
label—not message text—must mark only `interim_assistant_callback` as model
output. Separately, `agent:end` crosses from a worker thread to the event loop;
a fast normal final send can race ahead of that hook. Capture the completed
`_run_agent_inner` result before delivery, using its post-fallback `model` and
exact `final_response` signature. Do not broaden either rule to arbitrary
status traffic or chat-wide active-model inference.

Stable runtime markers: `_hermes_wechat_interim_origin_v1` and
`_hermes_wechat_model_route_v4`.

### Repeated `/approve` or `/continue` was lost

The sender+content fingerprint treated a fresh identical slash command as a
replay. Distinct provider message IDs are distinct controls; the same provider
message ID remains a replay. Two early `/approve` messages do not reserve
approval for a future request: each resolves the oldest request already pending
when it is handled.

2026-10-02 follow-up: the exemption module and its isolated test existed, but
the native v0.21 `gateway:startup` path installed only the footer wrapper. This
made verification green while the live adapter still used core content dedup.
The v0.21 startup function must install both wrappers atomically and expose
`fresh_slash_command_content_dedup_exemption=true` in its runtime receipt. The
integrated startup test must send three fresh `/approve` messages without
calling the exemption helper separately.

### Only `/continue` refreshed Context Token

Refresh was incorrectly placed in the special-command branch. Persist a fresh
token before ordinary content dedup/routing for every inbound message;
`/continue` only suppresses conversation routing.

### A fresh token still failed to drain during adapter cooldown

Context freshness and transport readiness are independent. A `/continue` may
arrive with a valid 24-hour token while the adapter is still inside the short
process-wide cooldown created by a preceding 429. A single synchronous drain
then records the failure and swallows `/continue`, leaving the queue dormant
until another inbound message.

The runtime must schedule one coalesced, bounded delayed retry per peer for
transient cooldown/rate-limit/timeout failures. It reuses the newest token,
keeps FIFO and acknowledgement-before-dequeue semantics, and stops on permanent
errors or after the retry bound. Repeated inbound messages may attempt an
immediate drain but must not create duplicate retry workers. Regression tests
must reproduce the real sequence: queued bubble → fresh `/continue` → cooldown
exception → no second user message → automatic FIFO recovery.

Startup readiness uses the same acknowledgement boundary. A successful
``adapter.send`` call can mean “accepted into the durable FIFO” when another
delivery is pending; it is not physical Weixin delivery. Startup logs therefore
say ``queued`` with the live pending count in that case and reserve “delivery
confirmed” for an actually acknowledged transport send.

The runtime receipt is refreshed after startup and after every inbound token
drain. The install-time snapshot alone is not authoritative because startup
notices and ordinary replies may enqueue new durable bubbles immediately after
the hook is installed.

### Startup-ready notification disappeared

Observed causes included opt-in-only configuration, wrong `HERMES_HOME`, a
suppression sentinel in an extra `.hermes` directory, and restarts that bypassed
the planned marker. Required behavior: default on, profile-scoped target,
one-shot suppression receipt, explicit system metadata, acknowledged logging.

### Markdown links and list items developed blank lines

The core formatter hard-wrapped source at a visual width. Weixin treats source
newlines as semantic Markdown. Normalize blocks without visual wrapping and
split only at the physical limit with a Markdown-aware splitter.

## Hermes v0.21 send-rail audit

Audit these boundaries before raising `requires_hermes`:

- `GatewayStreamConsumer.__init__`: turn model injection;
- `_send_or_edit` / `_first_send`: normal stream and final metadata;
- stream fallback helpers: final retry, tail sends, overflow continuations;
- `_finalize_boundary_stream`: pre-prompt fallback—the metadata-dropping rail
  found in the 2026-10-02 audit;
- approval, clarify, busy, progress, command, update, and lifecycle senders:
  remain Hermes-owned unless explicit model provenance exists;
- `WeixinAdapter.send` → format → split → `_send_text_chunk`: provenance remains
  active across every chunk and FIFO enqueue.

Search every `adapter.send(` call, but review structurally: the mere presence of
`metadata=` does not prove that edits, native streams, boundaries, or background
callbacks preserve the correct origin.

## Required regression matrix

No release is acceptable unless tests prove all of these together:

- two commentary bubbles use the actual model;
- direct non-streaming interim commentary uses the actual model while another
  `_send_status_text` call in the same turn remains `hermes`;
- a boundary preamble through the metadata-less fallback uses the actual model;
- the immediately following prompt uses `hermes`—no scope leak;
- approval, acknowledgement, and progress use `hermes` during an active turn;
- final answer after provider fallback uses the actual fallback model;
- a normal final send that beats the asynchronous `agent:end` hook still uses
  the completed result's actual fallback model;
- every multipart chunk uses the same actual model;
- failure + restart/FIFO drain preserves model and monotonic counters;
- ordinary and duplicate inbound messages refresh Context Token before dedup;
- fresh repeated slash commands pass; exact message-ID replay does not;
- long Markdown link/list lines remain unbroken at the transport boundary;
- startup-ready uses explicit `hermes` metadata and acknowledged delivery;
- install is idempotent, uninstall fails closed, and user state is preserved.

Run both the simulated matrix and the real Hermes v0.21 adapter/stream-consumer
test. A fake adapter alone is insufficient when the defect can live upstream in
Hermes' stream consumer.

## Documentation discipline

- `README.md` / `README_CN.md`: value, install, configuration, operations,
  privacy, troubleshooting—never an incident diary or patch inventory.
- `SKILL.md`: automation/install contract and safety gates.
- This memorandum: recurring failures, architectural reasoning, regressions.
- `MAINTAINER_REFERENCE.md`: legacy source-patch and migration reference.

When a visible footer or delivery defect is reported, update the invariant,
root-cause record, and regression matrix here in the same release. Do not wait
for the same defect class to be reported on a second send rail.
