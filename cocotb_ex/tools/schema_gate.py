#!/usr/bin/env python3
"""Schema gate for machine-readable artifacts (fail-closed).

Validates a JSON document against a JSON Schema.
Returns non-zero on any error.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"failed to parse json: {path} ({exc})") from exc


def main() -> int:
    p = argparse.ArgumentParser(description="Validate JSON artifact against JSON schema")
    p.add_argument("--input", required=True, help="JSON file to validate")
    p.add_argument("--schema", required=True, help="JSON schema file")
    p.add_argument("--label", default="artifact", help="log label")
    args = p.parse_args()

    input_path = Path(args.input)
    schema_path = Path(args.schema)

    if not input_path.exists():
        print(f"[SCHEMA_GATE][FAIL] {args.label}: input missing: {input_path}")
        return 2
    if not schema_path.exists():
        print(f"[SCHEMA_GATE][FAIL] {args.label}: schema missing: {schema_path}")
        return 2

    try:
        data = _load_json(input_path)
        schema = _load_json(schema_path)
    except ValueError as exc:
        print(f"[SCHEMA_GATE][FAIL] {args.label}: {exc}")
        return 2

    try:
        import jsonschema
        jsonschema.validate(instance=data, schema=schema)
    except Exception as exc:
        print(f"[SCHEMA_GATE][FAIL] {args.label}: schema validation failed")
        print(f"[SCHEMA_GATE][FAIL] detail: {exc}")
        return 1

    print(f"[SCHEMA_GATE][OK] {args.label}: {input_path} conforms to {schema_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
