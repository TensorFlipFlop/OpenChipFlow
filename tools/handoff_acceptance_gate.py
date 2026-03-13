#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"[HANDOFF][FAIL] failed to parse JSON {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"[HANDOFF][FAIL] JSON root must be an object: {path}")
    return raw


def semantic_pass(mode: str, review: dict[str, Any] | None) -> tuple[bool, str]:
    normalized = (mode or "").strip().lower() or "required"
    if normalized == "off":
        return True, "semantic review disabled"
    if normalized == "auto" and review is None:
        return True, "semantic review skipped in auto mode"
    if review is None:
        return False, "semantic review output missing"
    status = str(review.get("status", "")).strip().lower()
    if status == "pass":
        return True, "semantic review passed"
    if normalized == "auto" and status in {"", "skipped"}:
        return True, "semantic review skipped in auto mode"
    return False, f"semantic review status={status or 'missing'}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge handoff contract + semantic review into a final acceptance verdict")
    ap.add_argument("--contract-audit", required=True)
    ap.add_argument("--semantic-review", required=True)
    ap.add_argument("--acceptance-json", required=True)
    ap.add_argument("--semantic-review-mode", default="required")
    args = ap.parse_args()

    contract_path = Path(args.contract_audit).expanduser().resolve()
    semantic_path = Path(args.semantic_review).expanduser().resolve()
    acceptance_path = Path(args.acceptance_json).expanduser().resolve()

    contract = load_json(contract_path)
    semantic = load_json(semantic_path) if semantic_path.exists() else None

    contract_status = str(contract.get("status", "")).strip().lower()
    contract_ok = contract_status == "pass"
    semantic_ok, semantic_reason = semantic_pass(args.semantic_review_mode, semantic)
    final_ok = contract_ok and semantic_ok

    payload = {
        "schema_version": "handoff_acceptance/v1",
        "generated_at": datetime.now().isoformat(),
        "status": "pass" if final_ok else "needs_repair",
        "contract_status": contract_status or "unknown",
        "semantic_review_mode": (args.semantic_review_mode or "").strip().lower() or "required",
        "semantic_status": (str(semantic.get("status", "")).strip().lower() if isinstance(semantic, dict) else "missing"),
        "semantic_reason": semantic_reason,
        "contract_audit": str(contract_path),
        "semantic_review": str(semantic_path),
    }

    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if final_ok:
        print(f"[HANDOFF][OK] acceptance passed: {acceptance_path}")
        return 0

    print(f"[HANDOFF][FAIL] acceptance needs repair: {acceptance_path}")
    print(f"[HANDOFF][FAIL] contract_status={payload['contract_status']} semantic_reason={semantic_reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
