#!/usr/bin/env bash
# Build the CoCreate macOS app: dist/CoCreate.app -> dist/CoCreate.dmg (+ .pkg)
#
#   ./packaging/build_macos.sh [--pkg]
#
# Requires: macOS, Python 3.10+ on PATH. Run from the repo root.
# Note: the bundle includes torch, so the resulting app is large (~2.5 GB
# uncompressed, ~800 MB compressed dmg). Model weights are NOT bundled —
# they download to the user's HF cache on first run.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=.venv-build
python3 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --upgrade pip
pip install -e ".[dev]"

rm -rf dist build
pyinstaller --noconfirm packaging/cocreate.spec

APP="dist/CoCreate.app"
test -d "$APP" || APP="dist/CoCreate/CoCreate.app"
test -d "$APP" || { echo "error: .app not found under dist/"; exit 1; }

hdiutil create -volname "CoCreate" -srcfolder "$APP" -ov -format UDZO "dist/CoCreate.dmg"
echo "wrote dist/CoCreate.dmg"

if [ "${1:-}" = "--pkg" ]; then
  # pkgbuild installs --root verbatim; stage the .app so it lands in /Applications
  PKGROOT="$(mktemp -d)/root"
  mkdir -p "$PKGROOT"
  cp -R "$APP" "$PKGROOT/CoCreate.app"
  pkgbuild --root "$PKGROOT" \
    --install-location /Applications \
    --identifier com.cocreation.app \
    "dist/CoCreate-installer.pkg"
  echo "wrote dist/CoCreate-installer.pkg"
fi
