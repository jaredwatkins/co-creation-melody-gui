#!/usr/bin/env bash
# Install CoCreate on macOS — no Gatekeeper prompts.
#
# Downloads the signed-package-style .pkg and installs it with `installer`,
# which doesn't run the browser-download quarantine check. Paste into
# Terminal:
#
#   curl -fsSL https://raw.githubusercontent.com/jaredwatkins/co-creation-melody-gui/main/install.sh | bash
#
set -euo pipefail

REPO="jaredwatkins/co-creation-melody-gui"
APP="/Applications/CoCreate.app"

TAG="${1:-}"
if [ -z "$TAG" ]; then
  TAG=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
        | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')
fi
[ -n "$TAG" ] || { echo "error: could not determine latest release tag"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "Downloading CoCreate $TAG ..."
curl -fL "https://github.com/$REPO/releases/download/$TAG/CoCreate-installer.pkg" \
     -o "$TMP/CoCreate-installer.pkg"

echo "Installing to $APP (asks for your Mac password) ..."
sudo installer -pkg "$TMP/CoCreate-installer.pkg" -target /

# Belt and suspenders: strip quarantine if anything managed to acquire it.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "Done — launching CoCreate."
open "$APP"
