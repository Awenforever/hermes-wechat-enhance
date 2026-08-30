from __future__ import annotations

import asyncio
import contextvars
import functools
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import gateway.platforms.weixin as wx

MARKER = "HERMES_WECHAT_CURRENT_OFFICIAL_RUNTIME_COMPAT_CANDIDATE_V1"
EXPECTED_WEIXIN_SHA256 = "85e06cea1673ae20e336820e9cac5a7dc467bdd8c2796a73c3e2bf1042c76dc4"

_BYPASS_MESSAGE_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "wechat_enhance_compat_bypass_message_id", default=None
)
_SLASH_CONTENT_KEY: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "wechat_enhance_compat_slash_content_key", default=None
)
_SKIP_BUDGET_REFRESH: contextvars.ContextVar[Optional[tuple[str, str, str]]] = contextvars.ContextVar(
    "wechat_enhance_compat_skip_budget_refresh", default=None
)

_CLASSES_PATCHED = False
_ORIGINAL_BUDGET_UPDATE = None
_ORIGINAL_BUDGET_RESTORE = None


def _ensure_generation_entry(store: Any, account_id: str, user_id: str) -> Dict[str, Any]:
    key = store._key(account_id, user_id)
    entry = store._cache.get(key)
    if entry is None:
        entry = {
            "token": "",
            "count": 0,
            "updated_at": time.time(),
            "generation": 1,
        }
        store._cache[key] = entry
    else:
        generation = int(entry.get("generation", 0) or 0)
        if generation < 1:
            entry["generation"] = 1
    return entry


def _patch_classes() -> None:
    global _CLASSES_PATCHED, _ORIGINAL_BUDGET_UPDATE, _ORIGINAL_BUDGET_RESTORE
    if _CLASSES_PATCHED:
        return

    # Exact source gate: this compatibility candidate is not generic.
    source = Path(wx.__file__).read_bytes()
    if hashlib.sha256(source).hexdigest() != EXPECTED_WEIXIN_SHA256:
        raise RuntimeError("unsupported weixin.py hash for current-official runtime compatibility")

    # ContextTokenStore persistence inventory.
    def token_items_for_account(self: Any, account_id: str) -> Dict[str, str]:
        prefix = f"{account_id}:"
        return {
            key[len(prefix):]: value
            for key, value in self._cache.items()
            if key.startswith(prefix) and isinstance(value, str) and value
        }
    wx.ContextTokenStore.items_for_account = token_items_for_account

    _ORIGINAL_BUDGET_RESTORE = wx.ReplyBudgetStore.restore
    _ORIGINAL_BUDGET_UPDATE = wx.ReplyBudgetStore.update_token

    def budget_restore(self: Any, account_id: str) -> None:
        _ORIGINAL_BUDGET_RESTORE(self, account_id)
        prefix = f"{account_id}:"
        for key, entry in self._cache.items():
            if key.startswith(prefix) and isinstance(entry, dict):
                if int(entry.get("generation", 0) or 0) < 1:
                    entry["generation"] = 1

    def budget_update_token(self: Any, account_id: str, user_id: str, token: str) -> int:
        skip = _SKIP_BUDGET_REFRESH.get()
        if skip == (account_id, user_id, token):
            return int(_ensure_generation_entry(self, account_id, user_id).get("generation", 1))
        key = self._key(account_id, user_id)
        previous = self._cache.get(key) or {}
        generation = int(previous.get("generation", 0) or 0) + 1
        self._cache[key] = {
            "token": token,
            "count": 0,
            "updated_at": time.time(),
            "generation": generation,
        }
        self._persist(account_id)
        return generation

    def reconcile_from_context_tokens(self: Any, account_id: str, context_tokens: Dict[str, str]) -> int:
        changed = 0
        for user_id, token in context_tokens.items():
            if not isinstance(token, str) or not token:
                continue
            key = self._key(account_id, user_id)
            entry = self._cache.get(key)
            if not entry or entry.get("token") != token:
                previous_generation = int((entry or {}).get("generation", 0) or 0)
                self._cache[key] = {
                    "token": token,
                    "count": 0,
                    "updated_at": time.time(),
                    "generation": previous_generation + 1,
                }
                changed += 1
            elif int(entry.get("generation", 0) or 0) < 1:
                entry["generation"] = 1
        if changed:
            self._persist(account_id)
        return changed

    def budget_items_for_account(self: Any, account_id: str) -> Dict[str, Dict[str, Any]]:
        prefix = f"{account_id}:"
        return {
            key[len(prefix):]: dict(value)
            for key, value in self._cache.items()
            if key.startswith(prefix) and isinstance(value, dict)
        }

    def snapshot(self: Any, account_id: str, user_id: str) -> Dict[str, Any]:
        entry = self._cache.get(self._key(account_id, user_id))
        if not entry:
            return {"token": "", "count": 0, "updated_at": 0.0, "generation": 0}
        copied = dict(entry)
        if int(copied.get("generation", 0) or 0) < 1:
            copied["generation"] = 1
        return copied

    def get_generation(self: Any, account_id: str, user_id: str) -> int:
        entry = self._cache.get(self._key(account_id, user_id))
        if not entry:
            return 0
        generation = int(entry.get("generation", 0) or 0)
        return generation if generation >= 1 else 1

    def next_count(self: Any, account_id: str, user_id: str) -> int:
        return self.get_count(account_id, user_id) + 1

    def commit_count(self: Any, account_id: str, user_id: str, count: int) -> int:
        entry = _ensure_generation_entry(self, account_id, user_id)
        entry["count"] = max(int(entry.get("count", 0) or 0), int(count))
        entry["updated_at"] = time.time()
        self._persist(account_id)
        return int(entry["count"])

    def commit_count_if_generation(
        self: Any,
        account_id: str,
        user_id: str,
        expected_generation: int,
        count: int,
    ) -> bool:
        entry = self._cache.get(self._key(account_id, user_id))
        if not entry:
            return False
        generation = int(entry.get("generation", 0) or 0)
        if generation < 1:
            generation = 1
            entry["generation"] = generation
        if generation != int(expected_generation):
            return False
        entry["count"] = max(int(entry.get("count", 0) or 0), int(count))
        entry["updated_at"] = time.time()
        self._persist(account_id)
        return True

    def increment_and_get(self: Any, account_id: str, user_id: str) -> int:
        return self.commit_count(account_id, user_id, self.next_count(account_id, user_id))

    wx.ReplyBudgetStore.restore = budget_restore
    wx.ReplyBudgetStore.update_token = budget_update_token
    wx.ReplyBudgetStore.reconcile_from_context_tokens = reconcile_from_context_tokens
    wx.ReplyBudgetStore.items_for_account = budget_items_for_account
    wx.ReplyBudgetStore.snapshot = snapshot
    wx.ReplyBudgetStore.get_generation = get_generation
    wx.ReplyBudgetStore.next_count = next_count
    wx.ReplyBudgetStore.commit_count = commit_count
    wx.ReplyBudgetStore.commit_count_if_generation = commit_count_if_generation
    wx.ReplyBudgetStore.increment_and_get = increment_and_get

    # Delivery-ID-aware queue with non-destructive peek.
    def q_dedupe_key(self: Any, delivery_id: str, chunk_index: int) -> str:
        return f"{delivery_id}:{int(chunk_index)}"

    def q_normalize(self: Any, item: Any, position: int = 0) -> Dict[str, Any]:
        if isinstance(item, dict):
            return item
        content, chat_id, reply_to, metadata = item
        metadata_dict = dict(metadata or {})
        delivery_id = str(
            metadata_dict.get("_delivery_id")
            or metadata_dict.get("delivery_id")
            or f"legacy-{uuid.uuid4().hex}"
        ).strip()
        try:
            chunk_index = int(metadata_dict.get("_delivery_chunk_index", position))
        except Exception:
            chunk_index = position
        metadata_dict["_delivery_id"] = delivery_id
        metadata_dict["_delivery_chunk_index"] = chunk_index
        return {
            "content": content,
            "chat_id": chat_id,
            "reply_to": reply_to,
            "metadata": metadata_dict,
            "delivery_id": delivery_id,
            "chunk_index": chunk_index,
            "dedupe_key": q_dedupe_key(self, delivery_id, chunk_index),
            "enqueued_at": time.time(),
        }

    def q_enqueue(
        self: Any,
        account_id: str,
        user_id: str,
        content: str,
        chat_id: str,
        reply_to: Optional[str],
        metadata: Optional[Dict[str, Any]],
    ) -> bool:
        key = self._key(account_id, user_id)
        queue = self._queues.setdefault(key, [])
        metadata_dict = dict(metadata or {})
        delivery_id = str(
            metadata_dict.get("_delivery_id")
            or metadata_dict.get("delivery_id")
            or f"auto-{uuid.uuid4().hex}"
        ).strip()
        try:
            chunk_index = int(metadata_dict.get("_delivery_chunk_index", len(queue)))
        except Exception:
            chunk_index = len(queue)
        metadata_dict["_delivery_id"] = delivery_id
        metadata_dict["_delivery_chunk_index"] = chunk_index
        dedupe_key = q_dedupe_key(self, delivery_id, chunk_index)
        normalized = [q_normalize(self, item, i) for i, item in enumerate(queue)]
        self._queues[key] = normalized
        if any(str(item.get("dedupe_key")) == dedupe_key for item in normalized):
            return False
        normalized.append({
            "content": content,
            "chat_id": chat_id,
            "reply_to": reply_to,
            "metadata": metadata_dict,
            "delivery_id": delivery_id,
            "chunk_index": chunk_index,
            "dedupe_key": dedupe_key,
            "enqueued_at": time.time(),
        })
        return True

    def q_peek(self: Any, account_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        key = self._key(account_id, user_id)
        queue = self._queues.get(key)
        if not queue:
            return None
        item = q_normalize(self, queue[0], 0)
        queue[0] = item
        return item

    def q_dequeue(self: Any, account_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        key = self._key(account_id, user_id)
        queue = self._queues.get(key)
        if not queue:
            return None
        item = q_normalize(self, queue.pop(0), 0)
        if not queue:
            self._queues.pop(key, None)
        return item

    wx.MessageSendQueue._dedupe_key = q_dedupe_key
    wx.MessageSendQueue._normalize_compat_item = q_normalize
    wx.MessageSendQueue.enqueue = q_enqueue
    wx.MessageSendQueue.peek = q_peek
    wx.MessageSendQueue.dequeue = q_dequeue

    # Adapter methods.
    def context_delivery_lock(self: Any, chat_id: str) -> asyncio.Lock:
        locks = getattr(self, "_context_delivery_locks", None)
        if not isinstance(locks, dict):
            locks = {}
            self._context_delivery_locks = locks
        key = f"{self._account_id}:{chat_id}"
        lock = locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            locks[key] = lock
        return lock

    async def drain_pending(self: Any, chat_id: str) -> Any:
        last_message_id = None
        sent_any = False
        try:
            while True:
                async with context_delivery_lock(self, chat_id):
                    if not self._send_queue.has_pending(self._account_id, chat_id):
                        break
                    if self._budget_store.is_exhausted(self._account_id, chat_id):
                        pending = self._send_queue.pending_count(self._account_id, chat_id)
                        return wx.SendResult(
                            success=False,
                            message_id=last_message_id,
                            error=f"context_token budget exhausted; pending={pending}",
                        )

                    item = self._send_queue.peek(self._account_id, chat_id)
                    if item is None:
                        break
                    snapshot_value = self._budget_store.snapshot(self._account_id, chat_id)
                    context_token = (
                        self._budget_store.get_valid_token(self._account_id, chat_id)
                        or self._token_store.get(self._account_id, chat_id)
                    )
                    if int(snapshot_value.get("generation", 0) or 0) == 0:
                        self._budget_store.update_token(
                            self._account_id, chat_id, context_token or ""
                        )
                        snapshot_value = self._budget_store.snapshot(
                            self._account_id, chat_id
                        )

                    chunk = str(item.get("content") or "")
                    metadata = item.get("metadata")
                    metadata = metadata if isinstance(metadata, dict) else {}
                    model_name = wx._footer_model_name(metadata)
                    count = int(snapshot_value.get("count", 0) or 0) + 1
                    generation = int(snapshot_value.get("generation", 0) or 0)
                    chunk_with_footer = f"{chunk}\n\n---\n\n`{count}` `{model_name}`"
                    delivery_id = str(
                        item.get("delivery_id")
                        or metadata.get("_delivery_id")
                        or ""
                    ).strip()
                    try:
                        chunk_index = int(
                            item.get(
                                "chunk_index",
                                metadata.get("_delivery_chunk_index", 0),
                            )
                        )
                    except Exception:
                        chunk_index = 0
                    seed = (
                        f"{self._account_id}|{chat_id}|"
                        f"{delivery_id}|{chunk_index}"
                    )
                    client_id = (
                        "hermes-weixin-"
                        + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
                    )

                    await self._send_text_chunk(
                        chat_id=chat_id,
                        chunk=chunk_with_footer,
                        context_token=context_token,
                        client_id=client_id,
                    )
                    self._budget_store.commit_count_if_generation(
                        self._account_id, chat_id, generation, count
                    )
                    self._send_queue.dequeue(self._account_id, chat_id)
                    last_message_id = client_id
                    sent_any = True

                if (
                    self._send_chunk_delay_seconds > 0
                    and self._send_queue.has_pending(self._account_id, chat_id)
                ):
                    await asyncio.sleep(self._send_chunk_delay_seconds)
                else:
                    await asyncio.sleep(0)

            pending = self._send_queue.pending_count(self._account_id, chat_id)
            if pending:
                return wx.SendResult(
                    success=False,
                    message_id=last_message_id,
                    error=f"pending chunks remain: {pending}",
                )
            if sent_any:
                return wx.SendResult(success=True, message_id=last_message_id)
            return wx.SendResult(success=True, message_id=None)
        except Exception as exc:
            return wx.SendResult(
                success=False,
                message_id=last_message_id,
                error=str(exc),
            )

    async def send_media_with_budget(
        self: Any,
        chat_id: str,
        path: str,
        caption: Optional[str],
        metadata: Optional[Dict[str, Any]],
        *,
        force_file_attachment: bool = False,
    ) -> Any:
        if caption:
            caption_result = await self.send(
                chat_id=chat_id,
                content=caption,
                metadata=metadata,
            )
            if not caption_result.success:
                return caption_result

        async with context_delivery_lock(self, chat_id):
            if self._budget_store.is_exhausted(self._account_id, chat_id):
                return wx.SendResult(
                    success=False,
                    error="context_token budget exhausted; media not sent",
                )
            snapshot_value = self._budget_store.snapshot(self._account_id, chat_id)
            context_token = (
                self._budget_store.get_valid_token(self._account_id, chat_id)
                or self._token_store.get(self._account_id, chat_id)
            )
            if int(snapshot_value.get("generation", 0) or 0) == 0:
                self._budget_store.update_token(
                    self._account_id, chat_id, context_token or ""
                )
                snapshot_value = self._budget_store.snapshot(
                    self._account_id, chat_id
                )
            count = int(snapshot_value.get("count", 0) or 0) + 1
            generation = int(snapshot_value.get("generation", 0) or 0)
            try:
                message_id = await self._send_file(
                    chat_id,
                    path,
                    "",
                    force_file_attachment=force_file_attachment,
                )
            except Exception as exc:
                return wx.SendResult(success=False, error=str(exc))
            self._budget_store.commit_count_if_generation(
                self._account_id, chat_id, generation, count
            )
            return wx.SendResult(success=True, message_id=message_id)

    async def send_document(
        self: Any,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None,
        file_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        del file_name, reply_to, kwargs
        if not self._send_session or not self._token:
            return wx.SendResult(success=False, error="Not connected")
        return await send_media_with_budget(
            self, chat_id, file_path, caption, metadata
        )

    async def send_video(
        self: Any,
        chat_id: str,
        video_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        del reply_to
        if not self._send_session or not self._token:
            return wx.SendResult(success=False, error="Not connected")
        return await send_media_with_budget(
            self, chat_id, video_path, caption, metadata
        )

    async def send_voice(
        self: Any,
        chat_id: str,
        audio_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        del reply_to
        if not self._send_session or not self._token:
            return wx.SendResult(success=False, error="Not connected")
        fallback_caption = caption or "[voice message as attachment]"
        return await send_media_with_budget(
            self,
            chat_id,
            audio_path,
            fallback_caption,
            metadata,
            force_file_attachment=True,
        )

    wx.WeixinAdapter._context_delivery_lock = context_delivery_lock
    wx.WeixinAdapter._drain_pending = drain_pending
    wx.WeixinAdapter._send_media_with_budget = send_media_with_budget
    wx.WeixinAdapter.send_document = send_document
    wx.WeixinAdapter.send_video = send_video
    wx.WeixinAdapter.send_voice = send_voice

    _CLASSES_PATCHED = True


class _CompatDedupProxy:
    def __init__(self, delegate: Any):
        self._delegate = delegate

    def is_duplicate(self, key: Any) -> bool:
        bypass_id = _BYPASS_MESSAGE_ID.get()
        if bypass_id is not None and isinstance(key, str) and key == bypass_id:
            return False
        slash_key = _SLASH_CONTENT_KEY.get()
        if slash_key is not None and isinstance(key, str) and key == slash_key:
            return False
        return bool(self._delegate.is_duplicate(key))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


def _extract_text(message: Dict[str, Any]) -> str:
    return str(wx._extract_text(message.get("item_list") or []) or "")


def patch_weixin_adapter(adapter: Any) -> bool:
    _patch_classes()
    if getattr(adapter, "_hermes_wechat_current_official_runtime_compat_v1", False):
        return False

    # If the old dedicated slash wrapper is already present, unwrap it first.
    original_process = getattr(
        adapter,
        "_hermes_wechat_slash_dedup_original_process",
        getattr(adapter, "_process_message"),
    )
    original_dedup = getattr(
        adapter,
        "_hermes_wechat_slash_dedup_original_dedup",
        getattr(adapter, "_dedup"),
    )

    proxy = _CompatDedupProxy(original_dedup)
    adapter._dedup = proxy

    # Existing stores may have been restored before the startup Hook.
    try:
        adapter._budget_store.reconcile_from_context_tokens(
            adapter._account_id,
            adapter._token_store.items_for_account(adapter._account_id),
        )
    except Exception:
        pass

    @functools.wraps(original_process)
    async def wrapped_process(message: Dict[str, Any]) -> Any:
        sender_id = str(message.get("from_user_id") or "").strip()
        if not sender_id or sender_id == getattr(adapter, "_account_id", ""):
            return await original_process(message)

        message_id = str(message.get("message_id") or "").strip()
        if message_id and original_dedup.is_duplicate(message_id):
            return None

        text = _extract_text(message)
        normalized = text.strip()
        slash_key = None
        if normalized.startswith("/"):
            slash_key = (
                f"content:{sender_id}:"
                f"{hashlib.md5(text.encode()).hexdigest()}"
            )

        context_token = str(message.get("context_token") or "").strip()
        if context_token:
            async with adapter._context_delivery_lock(sender_id):
                adapter._token_store.set(
                    adapter._account_id, sender_id, context_token
                )
                # Call the enhanced class method directly for the one real refresh.
                wx.ReplyBudgetStore.update_token(
                    adapter._budget_store,
                    adapter._account_id,
                    sender_id,
                    context_token,
                )

        bypass_token = _BYPASS_MESSAGE_ID.set(message_id or None)
        slash_token = _SLASH_CONTENT_KEY.set(slash_key)
        skip_token = _SKIP_BUDGET_REFRESH.set(
            (adapter._account_id, sender_id, context_token)
            if context_token else None
        )
        try:
            return await original_process(message)
        finally:
            _SKIP_BUDGET_REFRESH.reset(skip_token)
            _SLASH_CONTENT_KEY.reset(slash_token)
            _BYPASS_MESSAGE_ID.reset(bypass_token)

    adapter._process_message = wrapped_process
    adapter._hermes_wechat_current_official_runtime_compat_v1 = True
    adapter._hermes_wechat_current_official_runtime_compat_original_process = original_process
    adapter._hermes_wechat_current_official_runtime_compat_original_dedup = original_dedup
    return True
