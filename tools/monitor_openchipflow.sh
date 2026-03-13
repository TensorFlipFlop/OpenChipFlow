#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="${1:?need log file}"
INTERVAL="${2:-300}"
STATUS_JSON="${LOG_FILE%.log}.status.json"
STATUS_MD="${LOG_FILE%.log}.status.md"

classify_error() {
  local text="$1"
  if echo "$text" | grep -Eqi 'oauth|fetch failed|api key|network|timeout|docker|command not found|permission denied|traceback|openai|gemini'; then
    echo "TOOLING"
  elif echo "$text" | grep -Eqi 'sim_fail\.log|regress_fail\.log|assert|test failed|mismatch|rtl|dut|testcase|verification'; then
    echo "TARGET"
  else
    echo "UNKNOWN"
  fi
}

while true; do
  ts=$(date -Iseconds)
  [[ -f "$LOG_FILE" ]] || { sleep "$INTERVAL"; continue; }

  last200=$(tail -n 200 "$LOG_FILE" || true)
  stage=$(echo "$last200" | grep -Eo '\[RUN\] [^:]+' | tail -n 1 || true)
  fail_line=$(echo "$last200" | grep -E '\[FAIL\]|Traceback|Error|ERROR|Exception|\[ERR\]' | tail -n 1 || true)

  state="RUNNING"
  reason=""
  category="N/A"

  if echo "$last200" | grep -q '\[END\].*rc=0'; then
    state="PASS"
  elif echo "$last200" | grep -q '\[END\].*rc='; then
    state="FAIL"
    category=$(classify_error "$last200")
    reason=$(echo "$last200" | grep -E '\[FAIL\]|Traceback|Error|ERROR|Exception|\[ERR\]|\[END\]' | tail -n 1 || true)
  elif [[ -n "$fail_line" ]]; then
    state="ERROR_DETECTED"
    category=$(classify_error "$last200")
    reason="$fail_line"
  fi

  cat > "$STATUS_JSON" <<EOF
{"time":"$ts","state":"$state","stage":"${stage:-N/A}","category":"$category","reason":$(printf '%s' "$reason" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}
EOF

  cat > "$STATUS_MD" <<EOF
# OpenChipFlow 运行状态
- time: $ts
- state: $state
- latest stage: ${stage:-N/A}
- category: $category
- reason: ${reason:-N/A}
EOF

  [[ "$state" == "PASS" || "$state" == "FAIL" ]] && break
  sleep "$INTERVAL"
done
