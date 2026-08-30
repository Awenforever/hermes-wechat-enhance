"""Runtime compatibility dispatcher for current official Hermes v0.18 Weixin.

For the exact current-official Weixin source hash, install the proven
skill-owned runtime compatibility layer without editing weixin.py.

For historical/hardened profiles, preserve the existing slash-command runtime
hook behavior because those profiles already receive their legacy 009/010/011
semantics through source patches.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

_MARKER = "HERMES_WECHAT_CURRENT_OFFICIAL_RUNTIME_COMPAT_HOOK_V1"
_CONTEXT_DISCOVERY_MARKER = "HERMES_WECHAT_CURRENT_OFFICIAL_CONTEXT_FIRST_ADAPTER_DISCOVERY_V1"
_ADAPTER_TYPE_GATE_MARKER = "HERMES_WECHAT_CURRENT_OFFICIAL_ADAPTER_TYPE_GATE_V1"
_CURRENT_OFFICIAL_WEIXIN_SHA256 = (
    "85e06cea1673ae20e336820e9cac5a7dc467bdd8c2796a73c3e2bf1042c76dc4"
)


def _iter_live_weixin_adapters(runner: Any) -> Iterable[Any]:
    seen: set[int] = set()
    collections = [getattr(runner, "adapters", None)]
    profile_adapters = getattr(runner, "_profile_adapters", None)
    if isinstance(profile_adapters, dict):
        collections.extend(profile_adapters.values())
    for collection in collections:
        if not isinstance(collection, dict):
            continue
        for key, adapter in collection.items():
            key_value = getattr(key, "value", key)
            adapter_name = str(getattr(adapter, "name", "")).lower()
            if str(key_value).lower() != "weixin" and "weixin" not in adapter_name:
                continue
            ident = id(adapter)
            if ident in seen:
                continue
            seen.add(ident)
            yield adapter


def _iter_context_weixin_adapters(
    context: Optional[Dict[str, Any]],
) -> Iterable[Any]:
    if not isinstance(context, dict):
        return

    seen: set[int] = set()
    collections = [context.get("adapters"), context.get("_profile_adapters")]
    for collection in collections:
        if not isinstance(collection, dict):
            continue
        for key, adapter in collection.items():
            key_value = getattr(key, "value", key)
            adapter_name = str(getattr(adapter, "name", "")).lower()
            if str(key_value).lower() != "weixin" and "weixin" not in adapter_name:
                continue
            ident = id(adapter)
            if ident in seen:
                continue
            seen.add(ident)
            yield adapter


def _current_weixin_digest() -> str:
    from gateway.platforms import weixin as official_weixin
    return hashlib.sha256(Path(official_weixin.__file__).read_bytes()).hexdigest()


def _is_current_official_weixin_adapter(adapter: Any) -> bool:
    from gateway.platforms import weixin as official_weixin
    return isinstance(adapter, official_weixin.WeixinAdapter)


async def install_weixin_runtime_compat_hook(
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    digest = _current_weixin_digest()
    if digest != _CURRENT_OFFICIAL_WEIXIN_SHA256:
        from hermes_wechat_enhance.slash_command_dedup import (
            install_slash_command_dedup_hook,
        )
        fallback = await install_slash_command_dedup_hook(context)
        logger.warning(
            "Hermes WeChat Enhance: %s profile=historical-fallback "
            "weixin_sha256=%s slash_marker=%s",
            _MARKER,
            digest,
            fallback.get("marker"),
        )
        return {
            "marker": _MARKER,
            "profile": "historical-fallback",
            "weixin_sha256": digest,
            "installed": int(fallback.get("installed", 0) or 0),
            "already": int(fallback.get("already", 0) or 0),
            "errors": list(fallback.get("errors", []) or []),
            "fallback": fallback,
        }

    from hermes_wechat_enhance.current_official_runtime_compat_core import (
        patch_weixin_adapter,
    )

    context_candidates = list(_iter_context_weixin_adapters(context))
    adapters = [
        adapter
        for adapter in context_candidates
        if _is_current_official_weixin_adapter(adapter)
    ]
    skipped_incompatible = len(context_candidates) - len(adapters)
    discovery_source = "hook-context"

    if context_candidates and not adapters:
        logger.info(
            "Hermes WeChat Enhance: %s profile=current-official-v018 "
            "discovery_source=hook-context skipped_incompatible=%d",
            _MARKER,
            skipped_incompatible,
        )
        return {
            "marker": _MARKER,
            "profile": "current-official-v018",
            "weixin_sha256": digest,
            "discovery_source": discovery_source,
            "installed": 0,
            "already": 0,
            "skipped_incompatible": skipped_incompatible,
            "errors": [],
        }

    if not adapters:
        discovery_source = "gateway-runner-fallback"
        try:
            from gateway.run import _gateway_runner_ref
            runner = _gateway_runner_ref()
        except Exception as exc:
            message = f"gateway runner fallback unavailable: {exc}"
            logger.error("Hermes WeChat Enhance: %s %s", _MARKER, message)
            return {
                "marker": _MARKER,
                "profile": "current-official-v018",
                "weixin_sha256": digest,
                "discovery_source": discovery_source,
                "installed": 0,
                "already": 0,
                "skipped_incompatible": skipped_incompatible,
                "errors": [message],
            }
        if runner is not None:
            runner_candidates = list(_iter_live_weixin_adapters(runner))
            adapters = [
                adapter
                for adapter in runner_candidates
                if _is_current_official_weixin_adapter(adapter)
            ]
            skipped_incompatible += len(runner_candidates) - len(adapters)

    if not adapters:
        message = "no live current-official WeixinAdapter found"
        logger.error("Hermes WeChat Enhance: %s %s", _MARKER, message)
        return {
            "marker": _MARKER,
            "profile": "current-official-v018",
            "weixin_sha256": digest,
            "discovery_source": discovery_source,
            "installed": 0,
            "already": 0,
            "skipped_incompatible": skipped_incompatible,
            "errors": [message],
        }

    installed = 0
    already = 0
    errors = []
    for adapter in adapters:
        try:
            if patch_weixin_adapter(adapter):
                installed += 1
            else:
                already += 1
        except Exception as exc:
            errors.append(str(exc))
            logger.exception(
                "Hermes WeChat Enhance: %s adapter patch failed: %s",
                _MARKER,
                exc,
            )

    if installed or already:
        logger.warning(
            "Hermes WeChat Enhance: %s profile=current-official-v018 "
            "discovery_source=%s installed=%d already=%d errors=%d",
            _MARKER,
            discovery_source,
            installed,
            already,
            len(errors),
        )
    else:
        logger.error(
            "Hermes WeChat Enhance: %s no live Weixin adapter found",
            _MARKER,
        )
    return {
        "marker": _MARKER,
        "profile": "current-official-v018",
        "weixin_sha256": digest,
        "discovery_source": discovery_source,
        "installed": installed,
        "already": already,
        "skipped_incompatible": skipped_incompatible,
        "errors": errors,
    }
