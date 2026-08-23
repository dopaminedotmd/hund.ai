#!/usr/bin/env bash
# Hund CLI installer — macOS/Linux.
#
# SECURITY: Detta skript hämtar och exekverar kod från internet.
# För produktionsanvändning, pinna till en release-SHA och verifiera
# SHA256-checksumman för detta skript innan du kör det.
#
# SHA-PINNING (rekommenderas för stable):
#   Sätt HUND_RELEASE_SHA till önskat commit SHA (minst 7 tecken).
#   Installeraren checkar ut den pinnade committen istf branch-HEAD.
#   Exempel:
#     HUND_RELEASE_SHA=37947cb bash install.sh
#
# CHECKSUM-VERIFIERING (för CI/release-pipeline):
#   sha256sum install.sh  # jämför mot manifest.install_sh_sha256
#
# DEV-LÄGE: Utan HUND_RELEASE_SHA hämtas latest main — OK för dev,
#   EJ för publik stable.
set -euo pipefail

REPO="https://github.com/dopaminedotmd/hund.ai"
TARGET="${HUND_HOME_DIR:-$HOME/.hund-cli}"
RELEASE_SHA="${HUND_RELEASE_SHA:-}"  # tom = dev-läge (latest main)

command -v git > /dev/null || { echo "git saknas"; exit 1; }

if ! command -v uv > /dev/null; then
  echo "installerar uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ -f "$TARGET/pyproject.toml" ]; then
  echo "uppdaterar $TARGET ..."
  git -C "$TARGET" fetch origin
else
  echo "klonar till $TARGET ..."
  git clone "$REPO" "$TARGET"
fi

if [ -n "$RELEASE_SHA" ]; then
  echo "pinnar till release SHA: $RELEASE_SHA"
  git -C "$TARGET" checkout "$RELEASE_SHA"
else
  echo "VARNING: HUND_RELEASE_SHA ej satt — hämtar latest main (dev-läge, ej för publik stable)" >&2
  git -C "$TARGET" pull
fi

uv tool install --force --from "$TARGET" hund

echo "Klar. Testa:"
echo "  hund --version"
echo "  export HUND_API_KEY=sk-..."
echo "  hund"
