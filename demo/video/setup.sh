#!/usr/bin/env bash
# One-time setup for the Boby (Remotion) overlay workspace.
# Clones Boby next to this repo, installs it, and links the `creative` CLI.
# Boby renders locally; the first render downloads Chrome Headless Shell (~150 MB).
set -euo pipefail

BOBY_DIR="${BOBY_DIR:-$HOME/boby}"

if ! command -v bun >/dev/null 2>&1; then
  echo "bun not found. Install from https://bun.sh then re-run." >&2
  exit 1
fi

if [ ! -d "$BOBY_DIR/.git" ]; then
  echo "Cloning Boby into $BOBY_DIR"
  git clone https://github.com/ReyNeill/boby "$BOBY_DIR"
fi

cd "$BOBY_DIR"
git pull --ff-only || true
bun install
bun link   # makes `creative` (and `boby`) available on PATH for this checkout

echo
echo "Done. `creative --version` should work now."
echo "Next: bash demo/video/build.sh   (run from the repo root)"
