"""Hermes WeChat Enhance v2 plugin registration."""

from __future__ import annotations

from .plugin_cli import register_cli, wechat_enhance_command


def register(ctx) -> None:
    """Register the operator CLI; gateway behavior stays in the explicit hook."""
    ctx.register_cli_command(
        name="wechat-enhance",
        help="Install, inspect, and migrate Hermes Weixin enhancements",
        setup_fn=register_cli,
        handler_fn=wechat_enhance_command,
        description="Weixin audit and migration operations for Hermes v0.21.",
    )
