import json
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from tb_audit import audit_metrics, load_json, load_yaml  # type: ignore  # noqa: E402
from tb_metrics import compute_metrics  # type: ignore  # noqa: E402


def write_current_metrics(tb_root: Path, output_path: Path, include_tests: bool) -> dict:
    metrics = compute_metrics(tb_root, include_tests)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def audit_tb(
    baseline_path: Path,
    current_path: Path,
    policies_path: Path,
) -> list[str]:
    baseline = load_json(baseline_path)
    current = load_json(current_path)
    policies = load_yaml(policies_path)
    return audit_metrics(baseline, current, policies)
