"""Synchronize the independently installable provider from the backend source."""
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'backend/catalog_discovery.py'
GENERATED = ROOT / 'model-provider/catalog_discovery.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check only; do not write')
    args = parser.parse_args()
    expected = SOURCE.read_bytes()
    if args.check:
        if not GENERATED.is_file() or GENERATED.read_bytes() != expected:
            raise SystemExit('Generated catalog differs: run python scripts/sync_catalog.py')
        print('Catalog distribution matches the canonical backend source.')
    else:
        GENERATED.write_bytes(expected)
        print('Generated standalone provider catalog.')


if __name__ == '__main__':
    main()
