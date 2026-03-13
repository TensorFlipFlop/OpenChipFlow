#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"PyYAML required to read {path}: {exc}") from exc
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def audit_metrics(baseline: dict, current: dict, policies: dict) -> list[str]:
    errors = []
    audit = policies.get("audit", {})

    def check_min_delta(key: str, delta: int) -> None:
        min_delta = audit.get(key, {}).get("min_delta", 0)
        if delta < min_delta:
            errors.append(f"{key} delta {delta} < min_delta {min_delta}")

    def check_max_delta(key: str, delta: int) -> None:
        max_delta = audit.get(key, {}).get("max_delta", 0)
        if delta > max_delta:
            errors.append(f"{key} delta {delta} > max_delta {max_delta}")

    deltas = {
        "assertions": current.get("assertions", 0) - baseline.get("assertions", 0),
        "skips": current.get("skips", 0) - baseline.get("skips", 0),
        "xfails": current.get("xfails", 0) - baseline.get("xfails", 0),
        "case_count": current.get("case_count", 0) - baseline.get("case_count", 0),
    }

    check_min_delta("assertions", deltas["assertions"])
    check_max_delta("skips", deltas["skips"])
    check_max_delta("xfails", deltas["xfails"])
    check_min_delta("case_count", deltas["case_count"])

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit TB metrics against baseline")
    parser.add_argument("--baseline", default="cocotb_ex/artifacts/baseline_tb_metrics.json")
    parser.add_argument("--current", default="cocotb_ex/artifacts/current_tb_metrics.json")
    parser.add_argument("--policies", default="cocotb_ex/config/policies.yaml")
    parser.add_argument("--update-baseline", action="store_true", help="Replace baseline with current")
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    current_path = Path(args.current)
    policies = load_yaml(Path(args.policies))

    if args.update_baseline:
        baseline_path.write_text(current_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Baseline updated: {baseline_path}")
        return

    if not baseline_path.exists():
        raise SystemExit(f"Baseline not found: {baseline_path}")

    baseline = load_json(baseline_path)
    current = load_json(current_path)

    errors = audit_metrics(baseline, current, policies)
    if errors:
        for err in errors:
            print(f"[audit] ERROR: {err}")
        raise SystemExit(1)

    print("[audit] OK")


if __name__ == "__main__":
    main()
