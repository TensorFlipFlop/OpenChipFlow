#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


def _strip_code(text):
    return text.strip().strip("`")


def extract_testplan_rows(text):
    lines = text.splitlines()
    rows = []
    found_column = False
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and "Testcase" in line and "Test ID" in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if "Testcase" in cells and "Test ID" in cells:
                found_column = True
                idx_id = cells.index("Test ID")
                idx = cells.index("Testcase")
                i += 2  # Skip the separator row
                while i < len(lines) and lines[i].lstrip().startswith("|"):
                    row_cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    test_id = _strip_code(row_cells[idx_id]) if len(row_cells) > idx_id else ""
                    tc = _strip_code(row_cells[idx]) if len(row_cells) > idx else ""
                    if test_id or tc:
                        rows.append({"test_id": test_id, "testcase": tc})
                    i += 1
                continue
        i += 1
    return rows, found_column


def extract_test_functions(path):
    if not path.exists():
        return [], False
    text = path.read_text(encoding="utf-8")
    tests = re.findall(r"^(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, re.M)
    return tests, True


def load_schedule(path):
    if not path.exists():
        return [], False, True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], True, False
    if not isinstance(data, list):
        return [], True, False
    return data, False, False


def main():
    parser = argparse.ArgumentParser(description="Validate testcase mapping across testplan, schedule, and tests.")
    parser.add_argument("--testplan", required=True)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--tests", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()

    testplan_path = Path(args.testplan)
    schedule_path = Path(args.schedule)
    tests_path = Path(args.tests)

    issues = []

    testplan_missing = not testplan_path.exists()
    testplan_testcases = []
    testplan_case_ids = []
    missing_test_ids = []
    has_testcase_column = False
    if testplan_missing:
        issues.append("testplan_missing")
    else:
        testplan_text = testplan_path.read_text(encoding="utf-8")
        rows, has_testcase_column = extract_testplan_rows(testplan_text)
        for idx, row in enumerate(rows, start=1):
            test_id = row.get("test_id") or f"CASE_{idx:03d}"
            testcase = row.get("testcase", "")
            if not row.get("test_id"):
                missing_test_ids.append(test_id)
            if testcase:
                testplan_testcases.append(testcase)
            testplan_case_ids.append(test_id)
        if not has_testcase_column:
            issues.append("missing_testcase_column")
        if has_testcase_column and not testplan_testcases:
            issues.append("empty_testcase_column")
        if missing_test_ids:
            issues.append("missing_test_id")

    schedule_data, schedule_invalid, schedule_missing = load_schedule(schedule_path)
    schedule_testcases = []
    schedule_case_ids = []
    if schedule_missing:
        issues.append("schedule_missing")
    if schedule_invalid:
        issues.append("schedule_invalid")
    if not schedule_missing and not schedule_invalid:
        for item in schedule_data:
            if isinstance(item, dict):
                tc = item.get("testcase")
                if tc:
                    schedule_testcases.append(tc)
                else:
                    issues.append("schedule_missing_testcase_field")
                if "case_ids" in item:
                    case_ids = item.get("case_ids")
                    if isinstance(case_ids, list):
                        if not case_ids:
                            issues.append("schedule_empty_case_ids")
                        else:
                            schedule_case_ids.extend(case_ids)
                    else:
                        issues.append("schedule_case_ids_not_list")
                elif item.get("case_id"):
                    schedule_case_ids.append(item.get("case_id"))
            else:
                issues.append("schedule_item_not_object")

    test_file_testcases, tests_found = extract_test_functions(tests_path)
    if not tests_found:
        issues.append("tests_missing")
    elif not test_file_testcases:
        issues.append("no_tests_found")

    missing_in_tests = sorted(set(schedule_testcases) - set(test_file_testcases))
    missing_in_schedule = sorted(set(testplan_testcases) - set(schedule_testcases))
    missing_in_testplan = sorted(set(schedule_testcases) - set(testplan_testcases))
    missing_case_ids_in_schedule = sorted(set(testplan_case_ids) - set(schedule_case_ids))
    missing_case_ids_in_testplan = sorted(set(schedule_case_ids) - set(testplan_case_ids))

    if missing_in_tests:
        issues.append("schedule_testcases_missing_in_tests")
    if missing_in_schedule:
        issues.append("testplan_testcases_missing_in_schedule")
    if missing_in_testplan:
        issues.append("schedule_testcases_missing_in_testplan")
    if missing_case_ids_in_schedule:
        issues.append("testplan_case_ids_missing_in_schedule")
    if missing_case_ids_in_testplan:
        issues.append("schedule_case_ids_missing_in_testplan")

    missing_run_basic = "run_basic" not in test_file_testcases if tests_found else False
    if tests_found and missing_run_basic:
        issues.append("missing_run_basic")

    report = {
        "ok": len(issues) == 0,
        "issues": sorted(set(issues)),
        "testplan_missing": testplan_missing,
        "missing_testcase_column": not has_testcase_column,
        "testplan_testcases": sorted(set(testplan_testcases)),
        "testplan_case_ids": sorted(set(testplan_case_ids)),
        "schedule_missing": schedule_missing,
        "schedule_invalid": schedule_invalid,
        "schedule_testcases": sorted(set(schedule_testcases)),
        "schedule_case_ids": sorted(set(schedule_case_ids)),
        "tests_missing": not tests_found,
        "test_file_testcases": sorted(set(test_file_testcases)),
        "missing_in_tests": missing_in_tests,
        "missing_in_schedule": missing_in_schedule,
        "missing_in_testplan": missing_in_testplan,
        "missing_case_ids_in_schedule": missing_case_ids_in_schedule,
        "missing_case_ids_in_testplan": missing_case_ids_in_testplan,
        "missing_run_basic": missing_run_basic,
    }

    output = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        Path(args.report).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
