#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${OPENCHIPFLOW_REPO_URL:-https://gitee.com/your_org/open-chip-flow.git}"
REF="${OPENCHIPFLOW_REF:-master}"
INSTALL_DIR="${OPENCHIPFLOW_INSTALL_DIR:-$HOME/.local/share/openchipflow}"
BIN_DIR="${OPENCHIPFLOW_BIN_DIR:-$HOME/.local/bin}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[install] missing required command: $1" >&2
    exit 127
  }
}

need_cmd git
need_cmd python3

mkdir -p "$(dirname "$INSTALL_DIR")"
rm -rf "$INSTALL_DIR.tmp"

echo "[install] cloning $REPO_URL (ref=$REF) ..."
if git clone --depth=1 --branch "$REF" "$REPO_URL" "$INSTALL_DIR.tmp" >/dev/null 2>&1; then
  :
else
  echo "[install] branch clone failed, fallback to full clone + checkout"
  git clone "$REPO_URL" "$INSTALL_DIR.tmp"
  git -C "$INSTALL_DIR.tmp" checkout "$REF"
fi

rm -rf "$INSTALL_DIR"
mv "$INSTALL_DIR.tmp" "$INSTALL_DIR"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/openchipflow" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec python3 "$INSTALL_DIR/scripts/runner.py" "\$@"
EOF
chmod +x "$BIN_DIR/openchipflow"

ln -sf "$BIN_DIR/openchipflow" "$BIN_DIR/chipflow"

echo "[install] done"
echo "[install] binary: $BIN_DIR/openchipflow"
echo "[install] alias : $BIN_DIR/chipflow"
echo "[install] add to PATH if needed: export PATH=\"$BIN_DIR:\$PATH\""
