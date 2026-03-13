#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


ASSERT_RE = re.compile(r"\bassert\b")
SKIP_RE = re.compile(r"pytest\.mark\.skip|pytest\.skip")
XFAIL_RE = re.compile(r"pytest\.mark\.xfail|pytest\.xfail")
COCOTB_TEST_RE = re.compile(r"@cocotb\.test")
PYTEST_TEST_RE = re.compile(r"\bdef\s+test_")


def iter_files(root: Path, patterns: list[str]) -> list[Path]:
    files = []
    for pattern in patterns:
        files.extend(root.rglob(pattern))
    return [p for p in files if p.is_file() and "__pycache__" not in p.parts]


def scan_text(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "assertions": len(ASSERT_RE.findall(text)),
        "skips": len(SKIP_RE.findall(text)),
        "xfails": len(XFAIL_RE.findall(text)),
        "case_count": len(COCOTB_TEST_RE.findall(text)) + len(PYTEST_TEST_RE.findall(text)),
    }


def compute_metrics(tb_root: Path, include_tests: bool) -> dict:
    patterns = ["*.py", "*.sv"]
    files = iter_files(tb_root, patterns)
    if include_tests:
        tests_dir = tb_root.parent / "tests"
        if tests_dir.exists():
            files.extend(iter_files(tests_dir, ["*.py"]))

    totals = {"assertions": 0, "skips": 0, "xfails": 0, "case_count": 0}
    for path in files:
        metrics = scan_text(path)
        for key in totals:
            totals[key] += metrics[key]

    return {
        "tb_root": str(tb_root),
        "files_scanned": [str(p) for p in files],
        **totals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute TB metrics")
    parser.add_argument("--root", default="cocotb_ex/tb", help="TB root directory")
    parser.add_argument("--include-tests", action="store_true", help="Include cocotb_ex/tests")
    parser.add_argument("--output", help="Write JSON output to file")
    args = parser.parse_args()

    metrics = compute_metrics(Path(args.root), args.include_tests)
    payload = json.dumps(metrics, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
