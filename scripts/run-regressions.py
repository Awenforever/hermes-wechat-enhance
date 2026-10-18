#!/usr/bin/env python3
"""Run contracts in separate private profiles; no real channel/model sends.

With --hermes-root, imports the actual Core and fakes only physical transport
in native adapter tests. Without it, runs only explicitly self-contained tests.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PURE = (
    'test-install-state-source-path.py', 'test-plugin-cli-lifecycle.py',
    'test-slash-command-dedup-hook.py', 'test-startup-ready-target.py',
    'test-v021-bubble-footer.py', 'test-transport-receipt-publisher.py',
    'test-transport-withdrawal.py',
    'test-restart-drain.py',
    'test-hook-transaction.py',
    'test-btw-rail-provenance.py',
    'test-bg-rail-provenance.py',
)
NATIVE = ('test-v021-native-contract.py', 'test-v021-real-adapter.py',
          'test-fix-regressions-q1q2q5.py', 'test-fix-regressions-v320.py',
          'test-context-fill-call-boundary.py','test-final-origin-producer.py')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hermes-root', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tests = PURE + (NATIVE if args.hermes_root else ())
    with tempfile.TemporaryDirectory(prefix='enhance-regression-') as raw:
        for index, name in enumerate(tests):
            sandbox = Path(raw) / str(index)
            sandbox.mkdir(mode=0o700)
            env = dict(os.environ)
            env.update(HOME=str(sandbox), HERMES_HOME=str(sandbox / '.hermes'),
                       TMPDIR=str(sandbox), TEMP=str(sandbox), TMP=str(sandbox),
                       HERMES_WECHAT_ENHANCE_SOURCE_DIR=str(root),
                       PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
            command = [sys.executable, '-B', str(root / 'scripts' / name)]
            if args.hermes_root:
                core = str(args.hermes_root.resolve())
                env.update(HERMES_GATEWAY_SRC=core, PYTHONPATH=os.pathsep.join((core, str(root))))
                if name.startswith('test-transport-'):
                    command += ['--hermes-root', core]
            else:
                env['HERMES_GATEWAY_SRC'] = str(sandbox / 'nonexistent-core')
                env['PYTHONPATH'] = str(root)
            print('RUN=' + name, flush=True)
            result = subprocess.run(command, cwd=root, env=env, timeout=180, check=False)
            if result.returncode:
                raise SystemExit(result.returncode)
    print(f'ENHANCE_REGRESSION_PASS count={len(tests)} native={bool(args.hermes_root)}')


if __name__ == '__main__':
    main()
