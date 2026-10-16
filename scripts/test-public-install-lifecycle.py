"""Actual Core installer lifecycle using a fetched public Git clone, no Gateway."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--core', type=Path, required=True)
parser.add_argument('--public-clone', type=Path, required=True)
parser.add_argument('--revision', required=True)
parser.add_argument('--workspace', type=Path, help=argparse.SUPPRESS)
args = parser.parse_args()
expected_version = next(line.split(':', 1)[1].strip() for line in
    (args.public_clone/'plugin.yaml').read_text(encoding='utf-8').splitlines()
    if line.startswith('version:'))

if args.workspace is None:
    # Core's PM holds process-lifetime generation leases. On Windows, cleanup
    # must happen after that owning process exits and its atexit releases run.
    # Do not delete leases, suppress cleanup errors or mutate Core to pass.
    with tempfile.TemporaryDirectory(prefix='enhance-public-lifecycle-') as raw:
        subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                        *sys.argv[1:], '--workspace', raw], check=True, timeout=900)
    print('PUBLIC_GIT_INSTALL_UPGRADE_UNINSTALL_REINSTALL_OK')
    raise SystemExit(0)


def invoke_hook(installed, action, env):
    code = "import importlib.util,sys; s=importlib.util.spec_from_file_location('operator_plugin_cli',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); raise SystemExit(getattr(m,sys.argv[2])())"
    subprocess.run([sys.executable, '-B', '-c', code, str(installed/'plugin_cli.py'), action],
                   env=env, check=True, timeout=60)


if args.workspace is not None:
    root = args.workspace.resolve(strict=True)
    home = root/'profile'
    home.mkdir()
    os.environ.update(HOME=str(root), HERMES_HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
    sys.path.insert(0, str(args.core))
    from hermes_cli.plugins_cmd import _install_plugin_core, _remove_plugin_core
    # Docker bind ownership is deliberately different. Copy into our private
    # workspace, preserving Git objects; do not relax safe.directory globally.
    mirror = root/'public-mirror'
    shutil.copytree(args.public_clone, mirror,
                    ignore=shutil.ignore_patterns('upstream-hermes', '__pycache__'))
    origin = mirror.as_uri()
    # This local Git source is a freshly fetched public repository; no fixture
    # clone implementation, no network/prod profile inside this container.
    installed, manifest, name = _install_plugin_core(origin, force=False,
        ref='0ed29fbfdffaef12ede6c244fa7f0cb706e1a24e', scan_decision_cb=lambda result: True)
    assert manifest['version'] == '3.1.0'
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(args.core), str(installed))),
               HERMES_GATEWAY_SRC=str(args.core), HERMES_WECHAT_ENHANCE_SOURCE_DIR=str(installed))
    invoke_hook(installed, '_install_hook', env)
    data = home/'plugin-data/hermes-wechat-enhance'
    sentinels = {home/'synthetic-auth-state': b'preserve synthetic authorization',
                 data/'synthetic-user-customization': b'preserve user customization'}
    for path, value in sentinels.items():
        path.write_bytes(value)
    # Seed the actual old queue implementation in a separate interpreter.
    code = "from pathlib import Path; from hermes_wechat_enhance.v021_bubble_footer import PendingBubbleStore; import os; q=PendingBubbleStore(Path(os.environ['HERMES_HOME'])/'plugin-data/hermes-wechat-enhance/send-queue.sqlite3'); q.enqueue('synthetic-account','synthetic-peer','legacy-client','preserve legacy body','synthetic-old-model')"
    subprocess.run([sys.executable, '-B', '-c', code], env=env, check=True)
    installed, manifest, name = _install_plugin_core(origin, force=True,
        ref=args.revision, scan_decision_cb=lambda result: True)
    assert manifest['version'] == expected_version
    invoke_hook(installed, '_install_hook', env)
    invoke_hook(installed, '_install_hook', env)
    database = data/'send-queue.sqlite3'
    with closing(sqlite3.connect(database)) as db:
        row = db.execute('SELECT client_id,chunk,model FROM pending_bubbles').fetchone()
    assert row == ('legacy-client', 'preserve legacy body', 'synthetic-old-model')
    subprocess.run([sys.executable, '-B', str(installed/'scripts/verify-self-install.py')],
                   env=env, check=True, timeout=120)
    invoke_hook(installed, '_uninstall_hook', env)
    _remove_plugin_core(installed)
    assert not installed.exists() and database.exists()
    installed, manifest, name = _install_plugin_core(origin, force=False,
        ref=args.revision, scan_decision_cb=lambda result: True)
    invoke_hook(installed, '_install_hook', env)
    for path, value in sentinels.items():
        assert path.read_bytes() == value
    with closing(sqlite3.connect(database)) as db:
        assert db.execute('SELECT client_id,chunk,model FROM pending_bubbles').fetchone() == row
    # The installer/upgrade did not send, drain or drop the legacy obligation.
    print('PUBLIC_GIT_LIFECYCLE_WORKER_OK')
