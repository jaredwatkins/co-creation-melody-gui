#!/usr/bin/env bash
# Install CoCreate on macOS — no Gatekeeper prompts.
#
# Files fetched with curl never get a quarantine attribute, so the app
# installed this way opens like a normal download would. Paste into Terminal:
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
curl -fL "https://github.com/$REPO/releases/download/$TAG/CoCreate.dmg" -o "$TMP/CoCreate.dmg"

echo "Installing to $APP ..."
MNT=$(hdiutil attach -nobrowse -readonly "$TMP/CoCreate.dmg" \
      | grep -o '/Volumes/.*' | head -1)
cp -R "$MNT/CoCreate.app" "$TMP/"
hdiutil detach -quiet "$MNT"

if [ -d "$APP" ] && [ ! -w "$(dirname "$APP")" ]; then
  sudo rm -rf "$APP"
  sudo cp -R "$TMP/CoCreate.app" "$APP"
else
  rm -rf "$APP"
  cp -R "$TMP/CoCreate.app" "$APP"
fi

# Belt and suspenders: strip quarantine if anything managed to acquire it.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "Done — launching CoCreate."
open "$APP"
