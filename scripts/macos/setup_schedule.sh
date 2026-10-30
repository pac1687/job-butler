#!/usr/bin/env bash
set -euo pipefail

# Phase 4.1: Configure macOS wake schedule and LaunchAgent for Job Butler nightly batch
PLIST_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/com.user.jobpipeline.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.user.jobpipeline.plist"

echo "[1/3] Configuring macOS power management wake schedule (MTWRF 02:00:00)..."
echo "Note: Requires sudo privileges."
sudo pmset repeat wake MTWRF 02:00:00

echo "[2/3] Installing LaunchAgent plist to ${PLIST_DEST}..."
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DEST"

echo "[3/3] Loading LaunchAgent..."
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "Done! Verify status with: launchctl list | grep com.user.jobpipeline"

