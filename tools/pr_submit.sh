#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: tools/pr_submit.sh -t <title> [-b <body-file>] [-B <base>] [-H <head>] [--draft] [--auto-commit] [--commit-message <msg>] [--pathspec-file <file>] [--fetch-base]

Options:
  -t <title>      PR title (required)
  -b <body-file>  PR body markdown file
  -B <base>       Base branch (default: master)
  -H <head>       Head branch (default: current branch)
  --draft         Create draft PR
  --auto-commit   Stage (whitelist) and commit before PR gates
  --commit-message <msg>
                  Commit message used with --auto-commit
  --pathspec-file <file>
                  Path whitelist file for --auto-commit (one pathspec per line)
  --fetch-base    Try `git fetch origin <base>` before commit gate
EOF
}

TITLE=""
BODY_FILE=""
BASE="master"
HEAD=""
DRAFT=0
AUTO_COMMIT=0
COMMIT_MESSAGE="Automated PR: Implementation update with test results"
PATHSPEC_FILE=""
FETCH_BASE=0

build_manual_pr_url() {
  local origin_url repo_path
  origin_url="$(git remote get-url origin 2>/dev/null || true)"
  repo_path="$(printf '%s' "$origin_url" | sed -nE 's#^git@gitee.com:([^ ]+?)(\\.git)?$#\\1#p; s#^https?://gitee.com/([^ ]+?)(\\.git)?$#\\1#p' | head -n 1)"
  [[ -n "$repo_path" ]] || return 1
  printf 'https://gitee.com/%s/pull/new/%s:%s...%s:%s\n' "$repo_path" "$repo_path" "$HEAD" "$repo_path" "$BASE"
}

auto_commit_with_whitelist() {
  local stage_items=()
  local excludes=(
    ":(exclude)artifacts/**"
    ":(exclude)cocotb_ex/artifacts/**"
    ":(exclude)cocotb_ex/ai_cli_pipeline/logs/**"
    ":(exclude)ISSUE.md"
    ":(exclude)env_dev/doc/**"
  )
  if [[ -n "$PATHSPEC_FILE" ]]; then
    [[ -f "$PATHSPEC_FILE" ]] || { echo "[ERR] pathspec file missing: $PATHSPEC_FILE"; exit 2; }
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%"${line##*[![:space:]]}"}"
      line="${line#"${line%%[![:space:]]*}"}"
      [[ -z "$line" || "$line" == \#* ]] && continue
      stage_items+=("$line")
    done < "$PATHSPEC_FILE"
    [[ ${#stage_items[@]} -gt 0 ]] || { echo "[ERR] no valid pathspec entries in $PATHSPEC_FILE"; exit 2; }
  else
    stage_items=(".")
  fi

  echo "[INFO] auto-commit: staging with whitelist (${#stage_items[@]} entries)"
  git add -- "${stage_items[@]}" "${excludes[@]}"
  if git diff --cached --quiet; then
    echo "[INFO] auto-commit: no staged changes after whitelist filtering"
    return 0
  fi
  git commit -m "$COMMIT_MESSAGE"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t) TITLE="$2"; shift 2 ;;
    -b) BODY_FILE="$2"; shift 2 ;;
    -B) BASE="$2"; shift 2 ;;
    -H) HEAD="$2"; shift 2 ;;
    --draft) DRAFT=1; shift ;;
    --auto-commit) AUTO_COMMIT=1; shift ;;
    --commit-message) COMMIT_MESSAGE="$2"; shift 2 ;;
    --pathspec-file) PATHSPEC_FILE="$2"; shift 2 ;;
    --fetch-base) FETCH_BASE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1"; usage; exit 2 ;;
  esac
done

[[ -n "$TITLE" ]] || { echo "[ERR] missing -t <title>"; usage; exit 2; }

command -v gitee >/dev/null 2>&1 || { echo "[ERR] gitee not found"; exit 2; }

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "[ERR] not a git repo"; exit 2; }
cd "$REPO_ROOT"
echo "[INFO] repo root: $REPO_ROOT"

if [[ -z "$HEAD" ]]; then
  HEAD="$(git branch --show-current)"
fi
[[ -n "$HEAD" ]] || { echo "[ERR] cannot resolve current branch"; exit 2; }
git show-ref --verify --quiet "refs/heads/$HEAD" || { echo "[ERR] head branch not found locally: $HEAD"; exit 2; }

if [[ "$HEAD" == "master" || "$HEAD" == "main" ]]; then
  echo "[ERR] refuse to open PR from protected branch: $HEAD"
  exit 2
fi

if [[ $AUTO_COMMIT -eq 1 ]]; then
  auto_commit_with_whitelist
fi

if [[ $FETCH_BASE -eq 1 ]]; then
  if git fetch origin "$BASE" >/dev/null 2>&1; then
    echo "[INFO] base sync: origin/$BASE fetched"
  else
    echo "[WARN] base sync: failed to fetch origin/$BASE; continue with local refs"
  fi
fi

BASE_REF=""
if git show-ref --verify --quiet "refs/remotes/origin/$BASE"; then
  BASE_REF="origin/$BASE"
elif git show-ref --verify --quiet "refs/heads/$BASE"; then
  BASE_REF="$BASE"
fi

if [[ -n "$BASE_REF" ]]; then
  AHEAD_LOCAL="$(git rev-list --count "${BASE_REF}..${HEAD}" 2>/dev/null || echo 0)"
  if [[ "$AHEAD_LOCAL" -le 0 ]]; then
    echo "[ERR] no commits to PR: $HEAD is not ahead of $BASE_REF"
    exit 2
  fi
  echo "[INFO] commit gate: $HEAD ahead of $BASE_REF by $AHEAD_LOCAL commit(s)"
else
  echo "[WARN] base ref not found locally; skip commit-ahead gate (base=$BASE)"
fi

# ensure branch pushed and remote tip matches local tip
LOCAL_SHA="$(git rev-parse "$HEAD")"
REMOTE_SHA="$(git ls-remote --heads origin "$HEAD" | awk '{print $1}' | tail -n 1 || true)"
if [[ "$REMOTE_SHA" != "$LOCAL_SHA" ]]; then
  echo "[INFO] push gate: syncing $HEAD to origin (local=$LOCAL_SHA remote=${REMOTE_SHA:-none})"
  git push -u origin "$HEAD"
fi
REMOTE_SHA="$(git ls-remote --heads origin "$HEAD" | awk '{print $1}' | tail -n 1 || true)"
if [[ "$REMOTE_SHA" != "$LOCAL_SHA" ]]; then
  echo "[FAIL] push gate: origin/$HEAD is not up to date (local=$LOCAL_SHA remote=${REMOTE_SHA:-none})"
  exit 3
fi
echo "[OK] push gate: origin/$HEAD is up to date"

BODY_ARG=()
if [[ -n "$BODY_FILE" ]]; then
  [[ -f "$BODY_FILE" ]] || { echo "[ERR] body file missing: $BODY_FILE"; exit 2; }
  BODY_ARG=(-b "$(cat "$BODY_FILE")")
fi

CMD=(gitee pr create -t "$TITLE" -B "$BASE" -H "$HEAD")
if [[ $DRAFT -eq 1 ]]; then
  CMD+=(--draft)
fi
if [[ ${#BODY_ARG[@]} -gt 0 ]]; then
  CMD+=("${BODY_ARG[@]}")
fi

echo "[RUN] ${CMD[*]}"
set +e
OUTPUT="$(${CMD[@]} 2>&1)"
RC=$?
set -e

if [[ $RC -ne 0 ]]; then
  echo "[WARN] pr create failed rc=$RC"
  echo "$OUTPUT"
  echo "[INFO] retry with --skip-body"
  RETRY=(gitee pr create -t "$TITLE" -B "$BASE" -H "$HEAD" --skip-body)
  [[ $DRAFT -eq 1 ]] && RETRY+=(--draft)
  set +e
  OUTPUT="$(${RETRY[@]} 2>&1)"
  RC=$?
  set -e
fi

if [[ $RC -ne 0 ]]; then
  echo "[FAIL] PR create failed"
  echo "$OUTPUT"
  MANUAL_URL="$(build_manual_pr_url || true)"
  if [[ -n "$MANUAL_URL" ]]; then
    echo "[INFO] Manual PR URL: $MANUAL_URL"
  fi
  exit $RC
fi

echo "$OUTPUT"
URL="$(echo "$OUTPUT" | grep -Eo 'https://gitee.com/[^ ]+/pulls/[0-9]+' | tail -n 1 || true)"
if [[ -z "$URL" ]]; then
  echo "[FAIL] PR URL not found in gitee output"
  MANUAL_URL="$(build_manual_pr_url || true)"
  if [[ -n "$MANUAL_URL" ]]; then
    echo "[INFO] Manual PR URL: $MANUAL_URL"
  fi
  exit 4
fi
echo "[OK] PR URL: $URL"
