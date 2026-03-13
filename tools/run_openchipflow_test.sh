#!/usr/bin/env bash
set -euo pipefail

WORKFLOW="${1:-implement}"
INTERVAL="${2:-300}"
TIMEOUT_HOURS="${3:-3}"

mkdir -p artifacts/ops
TS=$(date +%Y%m%d_%H%M%S)
RUN_ID="openchipflow_${WORKFLOW}_${TS}"
LOG="artifacts/ops/${RUN_ID}.log"
META="artifacts/ops/${RUN_ID}.meta.json"
MON_OUT="artifacts/ops/${RUN_ID}.monitor.out"

nohup bash -lc '
  set -euo pipefail
  echo "[START] $(date -Iseconds)" >> "'$LOG'"

  set +e
  bash tools/git_gate_pre.sh >> "'$LOG'" 2>&1
  pre_rc=$?
  set -e
  if [[ $pre_rc -ne 0 ]]; then
    echo "[END] $(date -Iseconds) rc=$pre_rc" >> "'$LOG'"
    exit $pre_rc
  fi

  set +e
  PYTHONUNBUFFERED=1 stdbuf -oL -eL timeout "'$TIMEOUT_HOURS'h" python3 cocotb_ex/ai_cli_pipeline/run_pipeline.py --workflow "'$WORKFLOW'" >> "'$LOG'" 2>&1
  run_rc=$?
  bash tools/git_gate_post.sh "'$LOG'" >> "'$LOG'" 2>&1
  post_rc=$?
  set -e

  # 优先返回运行失败，否则返回git gate失败
  rc=$run_rc
  if [[ $rc -eq 0 && $post_rc -ne 0 ]]; then
    rc=$post_rc
  fi

  echo "[END] $(date -Iseconds) rc=$rc" >> "'$LOG'"
  exit $rc
' >/dev/null 2>&1 &
RUN_PID=$!

nohup tools/monitor_openchipflow.sh "$LOG" "$INTERVAL" > "$MON_OUT" 2>&1 &
MON_PID=$!

cat > "$META" <<EOF
{"run_id":"$RUN_ID","workflow":"$WORKFLOW","interval_sec":$INTERVAL,"timeout_hours":$TIMEOUT_HOURS,"run_pid":$RUN_PID,"monitor_pid":$MON_PID,"log":"$LOG","status_json":"${LOG%.log}.status.json","status_md":"${LOG%.log}.status.md","monitor_out":"$MON_OUT","start_time":"$(date -Iseconds)"}
EOF

echo "$META"
