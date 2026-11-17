#!/usr/bin/env python3
"""Explicit local development installer. Never run by an installed catalog plugin.

Uses Hermes's own installer; does not copy/edit Hermes code or self-update.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for folder in ('model-provider', 'backend'):
        args = ['hermes', 'plugins', 'install', str(ROOT / folder)]
        if folder == 'backend': args.append('--enable')
        print('Installing OmniRoute component:', folder, flush=True)
        result = subprocess.run(args, check=False)
        if result.returncode:
            print(f'Hermes plugin install failed: {folder} ({result.returncode})', file=sys.stderr)
            return result.returncode
    print('Both components installed. Configure OMNIROUTE_BASE_URL and OMNIROUTE_API_KEY through Hermes.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
