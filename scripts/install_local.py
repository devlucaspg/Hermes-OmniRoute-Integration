#!/usr/bin/env python3
"""Install OmniRoute plugins from the public GitHub repository, pinned to this checkout.

Supports main and feature branches: the exact local HEAD commit is fetched from
GitHub. Uncommitted local changes are intentionally not deployed.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git"
COMPONENTS = ("model-provider", "backend")


def current_revision():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD^{commit}"],
        capture_output=True, text=True, check=False,
    )
    revision = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        print(
            "ERROR: this directory must be a Git checkout. Clone the repository "
            "from GitHub (and select the desired branch) before installing. "
            "Details: " + result.stderr.strip(),
            file=sys.stderr,
        )
        return None
    return revision.lower()


def main():
    for component in COMPONENTS:
        if not (ROOT / component / "plugin.yaml").is_file():
            print(f"ERROR: missing component: {component}", file=sys.stderr)
            return 2

    revision = current_revision()
    if not revision:
        return 2

    print(f"Installing OmniRoute from GitHub at commit {revision}", flush=True)
    for component in COMPONENTS:
        source = f"{REPOSITORY}#{component}"
        args = ["hermes", "plugins", "install", source, "--ref", revision]
        if component == "backend":
            args.append("--enable")
        print(f"Installing OmniRoute component: {component}", flush=True)
        result = subprocess.run(args, check=False)
        if result.returncode:
            print(
                f"Hermes plugin install failed: {component} ({result.returncode})",
                file=sys.stderr,
            )
            return result.returncode

    print("Both components installed from GitHub at the pinned commit.")
    print("Configure OMNIROUTE_BASE_URL and OMNIROUTE_API_KEY through Hermes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
