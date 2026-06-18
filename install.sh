#!/usr/bin/env bash
# Hund CLI installer — macOS/Linux (stub; primär plattform är Windows).
# SECURITY TODO: pin to release SHA + checksum before public use.
set -euo pipefail

REPO="https://github.com/dopaminedotmd/hund-cli"
TARGET="${HUND_HOME_DIR:-$HOME/.hund-cli}"

command -v git >/dev/null || { echo "git saknas"; exit 1; }

if ! command -v uv >/dev/null; then
  echo "installerar uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ -f "$TARGET/pyproject.toml" ]; then
  echo "uppdaterar $TARGET ..."
  git -C "$TARGET" pull
else
  echo "klonar till $TARGET ..."
  git clone "$REPO" "$TARGET"
fi

uv tool install --force --from "$TARGET" hund-cli

echo "Klar. Testa:"
echo "  hund --version"
echo "  export HUND_API_KEY=sk-..."
echo "  hund"
