#!/bin/bash
set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

VERIFY_REPORT="{verify_report}"
if [ ! -e "$VERIFY_REPORT" ] && [ -e "cocotb_ex/$VERIFY_REPORT" ]; then
  VERIFY_REPORT="cocotb_ex/$VERIFY_REPORT"
fi

FAILURES_DIR="{failures_dir}"
if [ ! -e "$FAILURES_DIR" ] && [ -e "cocotb_ex/$FAILURES_DIR" ]; then
  FAILURES_DIR="cocotb_ex/$FAILURES_DIR"
fi

BODY_FILE=$(mktemp)
PATHSPEC_FILE=$(mktemp)
trap 'rm -f "$BODY_FILE" "$PATHSPEC_FILE"' EXIT

printf '## Summary\n- Automated implementation update.\n\n' > "$BODY_FILE"
printf '## Test Status\n' >> "$BODY_FILE"
if [ -f "$VERIFY_REPORT" ]; then
  sed -n '1,120p' "$VERIFY_REPORT" >> "$BODY_FILE"
else
  echo "Verification report not found: $VERIFY_REPORT" >> "$BODY_FILE"
fi

printf '\n## Known Failures\n' >> "$BODY_FILE"
if [ -d "$FAILURES_DIR" ] && ls "$FAILURES_DIR"/*.md >/dev/null 2>&1; then
  for failure in "$FAILURES_DIR"/*.md; do
    echo "- $(basename "$failure")" >> "$BODY_FILE"
    snippet=$(sed -n '/Reproduction Command/,$p' "$failure" | sed -n '1,40p')
    if [ -n "$snippet" ]; then
      printf '```text\n%s\n```\n\n' "$snippet" >> "$BODY_FILE"
    else
      echo "  - Reproduction command not found in file." >> "$BODY_FILE"
      echo >> "$BODY_FILE"
    fi
  done
else
  echo "All Tests Passed" >> "$BODY_FILE"
fi

cat > "$PATHSPEC_FILE" <<'EOF'
# PR auto-commit whitelist
cocotb_ex/rtl
cocotb_ex/tb
cocotb_ex/tests
cocotb_ex/filelists
cocotb_ex/tools
cocotb_ex/ai_cli_pipeline/specs
cocotb_ex/ai_cli_pipeline/verification
tools
config
README.md
README.en.md
Makefile
EOF

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

bash tools/pr_submit.sh \
  -t "Auto: Implementation Update" \
  -B master \
  -H "$CURRENT_BRANCH" \
  -b "$BODY_FILE" \
  --auto-commit \
  --commit-message "Automated PR: Implementation update with test results" \
  --pathspec-file "$PATHSPEC_FILE" \
  --fetch-base
