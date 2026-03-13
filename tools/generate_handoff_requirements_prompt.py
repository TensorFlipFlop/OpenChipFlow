#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from handoff_prompt_utils import (
    DEFAULT_RULES_PATH,
    DEFAULT_SCHEMA_PATH,
    requirements_prompt_from_files,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the pre-run OpenChipFlow handoff requirements prompt")
    ap.add_argument("--rules", default=DEFAULT_RULES_PATH, help="path to handoff rules YAML")
    ap.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA_PATH,
        help="path to artifact_handoff_manifest schema JSON",
    )
    ap.add_argument("--target-state", default="verify_ready", help="handoff target delivery state")
    ap.add_argument("--out", default="", help="optional output file path")
    args = ap.parse_args()

    prompt = requirements_prompt_from_files(
        rules_path=args.rules,
        schema_path=args.schema,
        target_state=args.target_state,
    )
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(prompt, encoding="utf-8")
        print(out_path)
        return 0
    print(prompt, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
