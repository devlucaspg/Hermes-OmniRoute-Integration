#!/usr/bin/env python3
"""Explicit offline-development installer for Hermes plugins.

Hermes 0.23.2 treats a bare local directory path as a GitHub repository slug.
Stage a small real *local* Git repository and use file://...#subdir URLs.
This is for local tests only. Public releases should install from GitHub.
No plugin is installed or enabled automatically without running this script.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ('model-provider', 'backend')


def invoke(*args: str, cwd: Path | None = None) -> bool:
    result = subprocess.run(list(args), cwd=str(cwd) if cwd else None,
                            check=False)
    if result.returncode:
        print('Failed:', args[0], 'exit code', result.returncode, file=sys.stderr)
        return False
    return True


def main() -> int:
    for component in COMPONENTS:
        directory = ROOT / component
        if not (directory / 'plugin.yaml').is_file():
            print('Missing component:', directory, file=sys.stderr)
            return 2
        print('Validating', component, 'with the official Hermes validator', flush=True)
        if not invoke('hermes', 'plugins', 'validate', str(directory), '--install-deps'):
            return 2
    target = Path(os.environ.get('HERMES_HOME') or (Path.home() / '.hermes')) / 'local-sources'
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    clone = Path(tempfile.mkdtemp(prefix='omniroute-hermes-v0.4.0-beta.1-', dir=target))
    for component in COMPONENTS:
        shutil.copytree(ROOT / component, clone / component,
                        ignore=shutil.ignore_patterns('.env', '.git', '__pycache__', '*.pyc'))
    if not invoke('git', 'init', '-q', cwd=clone):
        return 2
    if not invoke('git', 'add', 'model-provider', 'backend', cwd=clone):
        return 2
    if not invoke('git', '-c', 'user.name=OmniRoute Local Installer',
                  '-c', 'user.email=local-installer@example.invalid',
                  'commit', '--quiet', '-m', 'Local OmniRoute test snapshot', cwd=clone):
        return 2
    print('Retained local Git source:', clone, flush=True)
    for component in COMPONENTS:
        local_url = clone.resolve().as_uri() + '#' + component
        command = ['hermes', 'plugins', 'install', local_url]
        if component == 'backend':
            command.append('--enable')
        print('Installing', component, 'from local Git source', flush=True)
        if not invoke(*command):
            print('Local source retained for troubleshooting:', clone, file=sys.stderr)
            return 2
    print('Components installed. Configure the API and models in Hermes.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
