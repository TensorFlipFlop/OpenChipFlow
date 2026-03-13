#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${OPENCHIPFLOW_INSTALL_DIR:-$HOME/.local/share/openchipflow}"
BIN_DIR="${OPENCHIPFLOW_BIN_DIR:-$HOME/.local/bin}"

rm -rf "$INSTALL_DIR"
rm -f "$BIN_DIR/openchipflow" "$BIN_DIR/chipflow"

echo "[uninstall] removed: $INSTALL_DIR"
echo "[uninstall] removed bins in: $BIN_DIR"
