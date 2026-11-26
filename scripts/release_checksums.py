"""Generate or verify the SHA-256 manifest for all tracked source files."""
from pathlib import Path
import argparse
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'RELEASE_SOURCE_SHA256SUMS.txt'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify manifest without writing')
    args = parser.parse_args()
    tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z'])
    paths = sorted({p.decode('utf-8') for p in tracked.split(b'\0') if p} - {MANIFEST})
    lines = []
    for path in paths:
        data = (ROOT / path).read_bytes()
        lines.append(f'{hashlib.sha256(data).hexdigest()}  {path}\n')
    expected = ''.join(lines).encode('utf-8')
    manifest = ROOT / MANIFEST
    if args.check:
        if not manifest.is_file() or manifest.read_bytes() != expected:
            raise SystemExit('Source checksum manifest is stale: run python scripts/release_checksums.py')
        print(f'SHA-256 verified for {len(paths)} tracked source files.')
    else:
        manifest.write_bytes(expected)
        print(f'SHA-256 generated for {len(paths)} tracked source files.')


if __name__ == '__main__':
    main()
