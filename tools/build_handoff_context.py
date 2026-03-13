#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from handoff_utils import HandoffError, build_handoff_context, load_handoff_manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Build normalized handoff context from a manifest")
    ap.add_argument("--manifest", required=True, help="path to artifact_handoff_manifest JSON")
    ap.add_argument("--workspace", default=".", help="pipeline workspace root")
    ap.add_argument(
        "--output",
        default="artifacts/handoff/handoff_context.json",
        help="output JSON path relative to workspace",
    )
    ap.add_argument(
        "--expect-state",
        default="",
        help="optional delivery_state value that must match",
    )
    args = ap.parse_args()

    try:
        manifest, manifest_file = load_handoff_manifest(args.manifest)
        context = build_handoff_context(
            manifest,
            manifest_file,
            args.workspace,
            expected_delivery_state=args.expect_state or None,
            context_output=args.output,
        )
    except HandoffError as exc:
        print(f"[HANDOFF][FAIL] {exc}")
        return 1

    out_path = Path(args.workspace).expanduser().resolve() / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    context["output"]["exists"] = True
    out_path.write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[HANDOFF][OK] wrote context: {out_path}")
    print(f"[HANDOFF][OK] case_id={context['case_id']} delivery_state={context['delivery_state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
