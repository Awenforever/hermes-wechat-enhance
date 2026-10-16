#!/usr/bin/env python3
"""Hook lifecycle never removes an active tree or publishes staging hooks."""
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hook_transaction_cli', ROOT/'plugin_cli.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

with tempfile.TemporaryDirectory(prefix='hook-transaction-') as raw:
    root = Path(raw)
    home, package = root/'profile', root/'package'
    home.mkdir()
    source = package/'hooks/hermes-wechat-enhance'
    shutil.copytree(ROOT/'hooks/hermes-wechat-enhance', source)
    constants = types.ModuleType('hermes_constants')
    constants.get_hermes_home = lambda: home
    sys.modules['hermes_constants'] = constants
    M._source_root = lambda: package
    target = home/'hooks/hermes-wechat-enhance'
    target.mkdir(parents=True)
    (target/'external.txt').write_text('preserve external hook', encoding='utf-8')
    config = home/'config.yaml'
    config.write_text('display:\n  busy_input_mode: interrupt\n', encoding='utf-8')
    assert M._install_hook() == 0
    cache = target/'__pycache__'
    cache.mkdir()
    cache_file = cache/'foreign-cache.pyc'
    cache_file.write_bytes(b'synthetic foreign-owned cache')
    cache_file.chmod(0o444)
    previous_hash = M._tree_hash(target)
    previous_manifest = M._install_manifest_path().read_bytes()
    cache_stat = cache_file.stat()
    rmtree = shutil.rmtree

    def no_active_delete(path, *args, **kwargs):
        assert Path(path) != target, 'recursive deletion of active hook'
        return rmtree(path, *args, **kwargs)

    with patch.object(shutil, 'rmtree', no_active_delete):
        assert M._install_hook() == 0
    assert cache_file.stat().st_mtime_ns == cache_stat.st_mtime_ns
    assert cache_file.read_bytes() == b'synthetic foreign-owned cache'
    # A changed package must stage outside Core's hook discovery tree.
    with (source/'handler.py').open('a', encoding='utf-8') as handle:
        handle.write('\n# synthetic changed source\n')
    original_replace = Path.replace

    def fail_activation(path, destination):
        if path.name == 'candidate' and Path(destination) == target:
            assert not path.is_relative_to(home/'hooks')
            raise PermissionError('synthetic activation failure')
        return original_replace(path, destination)

    with patch.object(Path, 'replace', fail_activation):
        try:
            M._install_hook()
        except PermissionError:
            pass
        else:
            raise AssertionError('activation failure was ignored')
    assert M._tree_hash(target) == previous_hash
    assert M._install_manifest_path().read_bytes() == previous_manifest
    # Failure after config update restores only this unchanged transaction.
    config.write_text('display:\n  busy_input_mode: interrupt\n', encoding='utf-8')
    before_config = config.read_bytes()
    with patch.object(M, '_write_manifest', side_effect=OSError('synthetic metadata failure')):
        try:
            M._install_hook()
        except OSError:
            pass
        else:
            raise AssertionError('manifest failure was ignored')
    assert M._tree_hash(target) == previous_hash and cache_file.exists()
    assert config.read_bytes() == before_config
    with patch.object(shutil, 'rmtree', no_active_delete):
        assert M._install_hook() == 0
        assert M._tree_hash(target) == M._tree_hash(source)
        assert [p.name for p in (home/'hooks').iterdir()] == ['hermes-wechat-enhance']
        assert M._uninstall_hook() == 0
    assert (target/'external.txt').read_text(encoding='utf-8') == 'preserve external hook'

print('HOOK_TRANSACTION_AND_CACHE_OWNERSHIP_OK')
