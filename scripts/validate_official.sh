#!/usr/bin/env bash
# Manual/offline-owner step: run the OFFICIAL Hermes validator once Hermes is installed.
# This script is outside both Marketplace subdirectory payloads, never auto-executed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${1:-$ROOT/hermes_official_validation.log}"
if ! command -v hermes >/dev/null 2>&1; then
  printf '%s\n' 'ERROR: Hermes CLI not found. Install/update Hermes before official validation.' | tee "$LOG" >&2
  exit 127
fi
{
  date -u +'%Y-%m-%dT%H:%M:%SZ'
  command -v hermes
  hermes --version || true
  printf '%s\n' '===== Hermes official validator: media/backend ====='
  hermes plugins validate "$ROOT/backend" --install-deps
  printf '%s\n' '===== Hermes official validator: LLM/model-provider ====='
  hermes plugins validate "$ROOT/model-provider" --install-deps
} 2>&1 | tee "$LOG"
