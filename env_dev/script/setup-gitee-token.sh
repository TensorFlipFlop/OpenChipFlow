#!/usr/bin/env bash
# OpenChipFlow - Gitee Token 快速配置脚本
# 使用方法: bash env_dev/script/setup-gitee-token.sh

set -euo pipefail

GITEE_BIN="$(command -v gitee 2>/dev/null || true)"
GITEE_DIR="$HOME/.gitee"
CONFIG_FILE="$GITEE_DIR/config.yml"

if [ -z "$GITEE_BIN" ]; then
  echo "❌ 未检测到 gitee CLI。请先安装："
  echo "   npm install -g @jj-h/gitee@latest"
  exit 1
fi

echo "=== OpenChipFlow: Gitee Token 配置向导 ==="
echo "gitee cli: $GITEE_BIN"

yaml_get() {
  local key="$1"
  local file="$2"
  if [ -f "$file" ]; then
    grep -E "^${key}:" "$file" | head -n 1 | sed -E 's/^[^:]+:\s*//; s/^"//; s/"$//' || true
  fi
}

OLD_USER_ID=""
OLD_USER_NAME=""
OLD_DEFAULT_PATH=""
OLD_COOKIES=""

if [ -f "$CONFIG_FILE" ]; then
  echo "✓ 已存在配置: $CONFIG_FILE"
  OLD_USER_ID="$(yaml_get user_id "$CONFIG_FILE")"
  OLD_USER_NAME="$(yaml_get user_name "$CONFIG_FILE")"
  OLD_DEFAULT_PATH="$(yaml_get default_path_with_namespace "$CONFIG_FILE")"
  OLD_COOKIES="$(yaml_get cookies_jar "$CONFIG_FILE")"
  echo
  read -r -p "是否重新配置? (y/N): " ans
  if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    echo "保持现有配置。"
    exit 0
  fi
  ts="$(date +%Y%m%d_%H%M%S)"
  cp "$CONFIG_FILE" "$CONFIG_FILE.backup.$ts"
  echo "旧配置已备份: $CONFIG_FILE.backup.$ts"
fi

cat <<'EOF'

====================================
  Gitee Token 获取步骤
====================================
1) 访问 https://gitee.com/settings/token
2) 生成新令牌（建议权限至少包含 projects, pull_requests）
3) 复制 Token（只显示一次）
====================================
EOF

echo
read -r -p "是否已获取 Token? (y/N): " ok
if [[ ! "$ok" =~ ^[Yy]$ ]]; then
  echo "请先获取 Token 后重试。"
  exit 1
fi

echo
read -r -p "请粘贴 Gitee Token: " GITEE_TOKEN
if [ -z "$GITEE_TOKEN" ]; then
  echo "❌ Token 不能为空"
  exit 1
fi

read -r -p "Gitee 用户名 [${OLD_USER_NAME:-your_gitee}]: " USER_NAME_INPUT
read -r -p "Gitee 用户 ID [${OLD_USER_ID:-12345678}]: " USER_ID_INPUT
read -r -p "默认仓库路径(default_path_with_namespace) [${OLD_DEFAULT_PATH:-your_org/open-chip-flow}]: " DEFAULT_PATH_INPUT

USER_NAME="${USER_NAME_INPUT:-${OLD_USER_NAME:-your_gitee}}"
USER_ID="${USER_ID_INPUT:-${OLD_USER_ID:-12345678}}"
DEFAULT_PATH="${DEFAULT_PATH_INPUT:-${OLD_DEFAULT_PATH:-your_org/open-chip-flow}}"
COOKIES_JAR="${OLD_COOKIES:-}"

mkdir -p "$GITEE_DIR"
cat > "$CONFIG_FILE" <<EOF
# Gitee CLI 配置文件
# 生成时间: $(date '+%Y-%m-%d %H:%M:%S')

access_token: "$GITEE_TOKEN"
api_prefix: "https://gitee.com/api/v5"
user_id: "$USER_ID"
user_name: "$USER_NAME"
default_ent_path: ""
default_path_with_namespace: "$DEFAULT_PATH"
cookies_jar: "$COOKIES_JAR"
EOF
chmod 600 "$CONFIG_FILE"

echo
echo "✓ 已写入配置: $CONFIG_FILE"
echo "✓ 权限已设置为 600"

echo
echo "=== 验证 ==="
if "$GITEE_BIN" --version >/dev/null 2>&1 && "$GITEE_BIN" pr create --help >/dev/null 2>&1; then
  echo "✓ gitee CLI 可用，PR 子命令可用。"
  echo "  示例: gitee pr create -t \"标题\" -B master -H <branch> -b \"描述\""
else
  echo "⚠️ 验证失败，请检查 token 或配置字段。"
  exit 2
fi

echo
echo "配置完成。"
TOKEN_LEN=${#GITEE_TOKEN}
if [ "$TOKEN_LEN" -gt 8 ]; then
  echo "Token: ${GITEE_TOKEN:0:4}***${GITEE_TOKEN: -3}"
else
  echo "Token: 已设置"
fi
