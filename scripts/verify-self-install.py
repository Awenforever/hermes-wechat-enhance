#!/usr/bin/env python3
"""One authoritative verifier for Hermes WeChat Enhance on current Hermes."""
from __future__ import annotations
import ast, json, os, py_compile, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
GATEWAY_SRC = Path(os.environ.get("HERMES_GATEWAY_SRC", "/opt/hermes"))
HOOK_DIR = Path(os.environ.get("HERMES_HOOKS_DIR", str(HERMES_HOME / "hooks"))) / "hermes-wechat-enhance"

def require(value, message):
    if not value: raise SystemExit("FAIL " + message)

def class_methods(path, class_name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return set()

def run_test(name, marker, gateway_python=False):
    path = ROOT / "scripts" / name
    require(path.is_file(), f"missing test {name}")
    interpreter = sys.executable
    if gateway_python:
        candidates = (GATEWAY_SRC / ".venv/bin/python3", GATEWAY_SRC / ".venv/bin/python", GATEWAY_SRC / ".venv/Scripts/python.exe")
        interpreter = str(next((p for p in candidates if p.is_file()), Path(sys.executable)))
    env = dict(os.environ)
    env.update(HERMES_GATEWAY_SRC=str(GATEWAY_SRC), HERMES_WECHAT_ENHANCE_SOURCE_DIR=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([interpreter, str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, check=False)
    print(result.stdout, end="")
    require(result.returncode == 0, f"{name} failed")
    require(marker in result.stdout, f"{name} did not emit {marker}")

def main():
    hook_yaml, handler = HOOK_DIR / "HOOK.yaml", HOOK_DIR / "handler.py"
    require(hook_yaml.is_file(), f"missing active hook manifest {hook_yaml}")
    require(handler.is_file(), f"missing active hook handler {handler}")
    handler_text = handler.read_text(encoding="utf-8")
    require("install_v021_bubble_footer_hook" in handler_text, "current runtime hook not installed")
    for forbidden in ("legacy_runtime_compat", "current_official_runtime_compat", "MessageSendQueue", "ReplyBudgetStore"):
        require(forbidden not in handler_text, f"active hook still references legacy contract: {forbidden}")
    wx = GATEWAY_SRC / "gateway/platforms/weixin.py"
    require(wx.is_file(), f"missing current Hermes adapter {wx}")
    methods = class_methods(wx, "WeixinAdapter")
    for name in ("_process_message", "_split_text", "_send_text_chunk", "send"):
        require(name in methods, f"unsupported current Hermes adapter: {name} missing")
    for path in list((ROOT / "hermes_wechat_enhance").glob("*.py")) + [handler]:
        py_compile.compile(str(path), doraise=True)
    print("CURRENT_HERMES_CAPABILITY_OK")
    run_test("test-v021-bubble-footer.py", "V021_BUBBLE_FOOTER_TEST_OK", gateway_python=True)
    run_test("test-v021-real-adapter.py", "V021_REAL_WEIXIN_ADAPTER_TEST_OK", gateway_python=True)
    run_test("test-slash-command-dedup-hook.py", "SLASH_COMMAND_DEDUP_HOOK_TEST=PASS")
    run_test("test-startup-ready-target.py", "WECHAT_STARTUP_TARGET_INHERIT_TEST=PASS")
    print(json.dumps({"ok": True, "contract": "HERMES_WECHAT_ENHANCE_CURRENT_V1", "core_mutation": False, "legacy_runtime": False}, sort_keys=True))
    print("SELF_INSTALL_VERIFY_OK")

if __name__ == "__main__": main()
