#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="${1:?need run log}"
PR_LOG="cocotb_ex/ai_cli_pipeline/logs/pr_submit.log"

status=0

branch=$(git rev-parse --abbrev-ref HEAD)
ahead=$(git status -sb | sed -n '1p' | sed -n 's/.*ahead \([0-9]\+\).*/\1/p')
ahead=${ahead:-0}

echo "[GIT_GATE] final branch=$branch ahead=$ahead"

# 1) 禁止最终停留 master/main（测试模板要求分支化验证）
if [[ "$branch" == "master" || "$branch" == "main" ]]; then
  echo "[GIT_GATE][FAIL][TOOLING] still on protected branch: $branch"
  status=2
fi

# 2) 若 pr_submit 显示明显失败，标记 TOOLING
if [[ -f "$PR_LOG" ]]; then
  if grep -Eqi "Read-only file system|Could not resolve hostname|授权错误|请在仓库目录下执行该命令|skill未找到|未授权|failed" "$PR_LOG"; then
    echo "[GIT_GATE][FAIL][TOOLING] pr_submit has blocking errors"
    grep -Ein "Read-only file system|Could not resolve hostname|授权错误|请在仓库目录下执行该命令|skill未找到|未授权|failed" "$PR_LOG" | tail -n 5 || true
    status=3
  fi
fi

# 3) 若日志有 END rc=0 且 ahead>0，说明本地提交未推远端，归因为 TOOLING（push/PR链路）
if grep -q "\[END\].*rc=0" "$LOG_FILE" && [[ "$ahead" -gt 0 ]]; then
  echo "[GIT_GATE][WARN][TOOLING] run passed but local ahead=$ahead (push likely not completed)"
fi

exit $status
