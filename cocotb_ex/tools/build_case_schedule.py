#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


def _strip_code(text):
    return text.strip().strip("`")


def _norm_case_id(raw, idx):
    text = _strip_code(raw)
    if not text:
        return f"CASE_{idx:03d}"
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return cleaned or f"CASE_{idx:03d}"


def parse_tables(text):
    lines = text.splitlines()
    items = []
    found_testcase_column = False
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and "Test ID" in line and "Testcase" in line:
            headers = [c.strip() for c in line.strip("|").split("|")]
            if "Test ID" not in headers or "Testcase" not in headers:
                i += 1
                continue
            found_testcase_column = True
            idx_id = headers.index("Test ID")
            idx_tc = headers.index("Testcase")
            idx_desc = headers.index("Description") if "Description" in headers else None
            i += 2  # skip separator
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                test_id = _strip_code(row[idx_id]) if len(row) > idx_id else ""
                testcase = _strip_code(row[idx_tc]) if len(row) > idx_tc else ""
                desc = _strip_code(row[idx_desc]) if idx_desc is not None and len(row) > idx_desc else ""
                if test_id or testcase or desc:
                    items.append((test_id, testcase, desc))
                i += 1
            continue
        i += 1
    return items, found_testcase_column


def main():
    parser = argparse.ArgumentParser(description="Build case_schedule.json from testplan Testcase column.")
    parser.add_argument("--testplan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    testplan_path = Path(args.testplan)
    if not testplan_path.exists():
        sys.stderr.write(f"[SCHEDULE][ERROR] Testplan not found: {testplan_path}\n")
        return 1

    text = testplan_path.read_text(encoding="utf-8")
    rows, found = parse_tables(text)
    if not found:
        sys.stderr.write("[SCHEDULE][ERROR] Testplan missing Testcase column.\n")
        return 1
    if not rows:
        sys.stderr.write("[SCHEDULE][ERROR] No testplan rows found.\n")
        return 1

    schedule = []
    errors = []
    grouped = {}
    order = []
    for idx, (test_id, testcase, desc) in enumerate(rows, start=1):
        if not testcase:
            errors.append(test_id or f"ROW_{idx}")
            continue
        case_label = test_id if test_id else _norm_case_id(test_id, idx)
        if testcase not in grouped:
            grouped[testcase] = {"case_ids": [], "descriptions": [], "first_idx": idx}
            order.append(testcase)
        grouped[testcase]["case_ids"].append(case_label)
        if desc:
            grouped[testcase]["descriptions"].append(f"{case_label}: {desc}")

    if errors:
        sys.stderr.write("[SCHEDULE][ERROR] Missing testcase in rows: " + ", ".join(errors) + "\n")
        return 1

    for testcase in order:
        group = grouped[testcase]
        case_ids = group["case_ids"]
        case_id = _norm_case_id(case_ids[0], group["first_idx"])
        description = " | ".join(group["descriptions"])
        schedule.append(
            {
                "case_id": case_id,
                "case_ids": case_ids,
                "testcase": testcase,
                "description": description,
            }
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schedule, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
