#!/usr/bin/env bash
set -euo pipefail

# 强制非 master 分支运行；若在 master 自动建分支
CUR=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CUR" == "master" || "$CUR" == "main" ]]; then
  TS=$(date +%Y%m%d_%H%M%S)
  BR="dev_${TS}"
  git checkout -b "$BR"
  echo "[GIT_GATE] switched branch: $BR"
else
  echo "[GIT_GATE] branch ok: $CUR"
fi

echo "[GIT_GATE] branch=$(git rev-parse --abbrev-ref HEAD)"
echo "[GIT_GATE] upstream=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo NO_UPSTREAM)"
