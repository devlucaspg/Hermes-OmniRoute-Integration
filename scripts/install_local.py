#!/usr/bin/env python3
"""Install both OmniRoute plugins from GitHub, pinned to this checkout's commit.

Works with main and feature branch checkouts. Local working-tree edits are not
installed; Hermes fetches the exact published commit from the canonical GitHub
repository. No local file:// Git staging or Hermes core modifications.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ("model-provider", "backend")
REPOSITORY = "https://github.com/devlucaspg/Hermes-OmniRoute-Integration.git"


def invoke(*args: str, cwd: Path | None = None) -> bool:
    result = subprocess.run(
        list(args), cwd=str(cwd) if cwd else None, check=False
    )
    if result.returncode:
        print("Failed:", args[0], "exit code", result.returncode, file=sys.stderr)
        return False
    return True


def current_revision() -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD^{commit}"],
        capture_output=True, text=True, check=False,
    )
    revision = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        print(
            "ERROR: clone the GitHub repository and checkout the desired branch "
            "before installing. A Git checkout is required for commit pinning. "
            "Details: " + result.stderr.strip(),
            file=sys.stderr,
        )
        return None
    return revision.lower()


def main() -> int:
    for component in COMPONENTS:
        directory = ROOT / component
        if not (directory / "plugin.yaml").is_file():
            print("Missing component:", directory, file=sys.stderr)
            return 2
        print("Validating", component, "with the official Hermes validator", flush=True)
        if not invoke("hermes", "plugins", "validate", str(directory), "--install-deps"):
            return 2

    revision = current_revision()
    if not revision:
        return 2

    print("Installing components from GitHub at commit:", revision, flush=True)
    for component in COMPONENTS:
        source = f"{REPOSITORY}#{component}"
        command = ["hermes", "plugins", "install", source, "--ref", revision]
        if component == "backend":
            command.append("--enable")
        print("Installing", component, "from GitHub", flush=True)
        if not invoke(*command):
            return 2

    print("Components installed from GitHub. Configure the API and models in Hermes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
