#!/usr/bin/env python3
"""Generate REQ->Testcase->RTL signal trace matrix.

Inputs:
- reqs markdown
- testplan markdown
- cocotb test file
- tb wrapper (for debug_* -> dut.* mapping)
- rtl file

Outputs:
- markdown matrix
- json matrix
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set


REQ_RE = re.compile(r"\bREQ-\d+\b")


@dataclass
class Requirement:
    req_id: str
    text: str


@dataclass
class TestplanRow:
    test_id: str
    req_ids: List[str]
    testcase: str
    desc: str


def _strip_code(text: str) -> str:
    return text.strip().strip("`")


def _split_markdown_row(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_requirements(reqs_md: Path) -> List[Requirement]:
    text = reqs_md.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    reqs: List[Requirement] = []
    cur_id = None
    cur_lines: List[str] = []

    for line in lines:
        m = re.match(r"^##\s+(REQ-\d+)\b", line.strip())
        if m:
            if cur_id is not None:
                reqs.append(Requirement(cur_id, " ".join([x.strip() for x in cur_lines if x.strip()])))
            cur_id = m.group(1)
            cur_lines = []
            continue

        if cur_id is not None:
            if line.strip().startswith("## "):
                # defensive flush for malformed heading cases
                reqs.append(Requirement(cur_id, " ".join([x.strip() for x in cur_lines if x.strip()])))
                cur_id = None
                cur_lines = []
            else:
                cur_lines.append(line)

    if cur_id is not None:
        reqs.append(Requirement(cur_id, " ".join([x.strip() for x in cur_lines if x.strip()])))

    return reqs


def parse_testplan(testplan_md: Path) -> List[TestplanRow]:
    text = testplan_md.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    rows: List[TestplanRow] = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and "Test ID" in line and "Testcase" in line:
            headers = _split_markdown_row(line)
            try:
                idx_id = headers.index("Test ID")
                idx_req = headers.index("Requirement(s)") if "Requirement(s)" in headers else headers.index("Requirement")
                idx_tc = headers.index("Testcase")
                idx_desc = headers.index("Description") if "Description" in headers else -1
            except ValueError:
                i += 1
                continue

            i += 2  # skip separator
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = _split_markdown_row(lines[i])
                test_id = _strip_code(cells[idx_id]) if len(cells) > idx_id else ""
                req_cell = _strip_code(cells[idx_req]) if len(cells) > idx_req else ""
                testcase = _strip_code(cells[idx_tc]) if len(cells) > idx_tc else ""
                desc = _strip_code(cells[idx_desc]) if idx_desc >= 0 and len(cells) > idx_desc else ""
                req_ids = REQ_RE.findall(req_cell)

                if test_id or testcase or req_ids:
                    rows.append(TestplanRow(test_id=test_id, req_ids=req_ids, testcase=testcase, desc=desc))
                i += 1
            continue
        i += 1

    return rows


def _extract_dut_signals_from_text(text: str, dut_prefix: str) -> Set[str]:
    signals: Set[str] = set()
    # Direct handle references: dut.signal or self.dut.signal
    signals.update(re.findall(rf"\b{re.escape(dut_prefix)}\.([A-Za-z_][A-Za-z0-9_]*)", text))
    # Backdoor string path references: "dut.signal"
    signals.update(re.findall(r"""["']dut\.([A-Za-z_][A-Za-z0-9_]*)["']""", text))
    return signals


def parse_tb_helper_signals(tb_py: Path) -> Dict[str, List[str]]:
    if not tb_py.exists():
        return {}

    text = tb_py.read_text(encoding="utf-8", errors="replace")
    defs = list(re.finditer(r"^\s*(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, re.M))
    if not defs:
        return {}

    direct_signals: Dict[str, Set[str]] = {}
    call_graph: Dict[str, Set[str]] = {}

    for idx, m in enumerate(defs):
        name = m.group(1)
        start = m.end()
        end = defs[idx + 1].start() if idx + 1 < len(defs) else len(text)
        body = text[start:end]

        sigs = _extract_dut_signals_from_text(body, "self.dut")
        direct_signals[name] = sigs
        call_graph[name] = set(re.findall(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", body))

    resolved: Dict[str, Set[str]] = {}

    def resolve(name: str, visiting: Set[str]) -> Set[str]:
        if name in resolved:
            return resolved[name]
        if name in visiting:
            return set()

        visiting_next = set(visiting)
        visiting_next.add(name)

        out = set(direct_signals.get(name, set()))
        for callee in call_graph.get(name, set()):
            if callee == name:
                continue
            out.update(resolve(callee, visiting_next))

        resolved[name] = out
        return out

    return {name: sorted(resolve(name, set())) for name in direct_signals}


def parse_testcase_signals(test_py: Path, tb_helper_signals: Dict[str, List[str]] | None = None) -> Dict[str, List[str]]:
    text = test_py.read_text(encoding="utf-8", errors="replace")
    defs = list(re.finditer(r"^(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, re.M))

    helper_map = tb_helper_signals or {}
    direct_signals: Dict[str, Set[str]] = {}
    call_graph: Dict[str, Set[str]] = {}

    defined_names = {m.group(1) for m in defs}
    for idx, m in enumerate(defs):
        name = m.group(1)
        start = m.end()
        end = defs[idx + 1].start() if idx + 1 < len(defs) else len(text)
        body = text[start:end]

        sigs = _extract_dut_signals_from_text(body, "dut")
        helper_calls = set(re.findall(r"\btb\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", body))
        for helper in helper_calls:
            sigs.update(helper_map.get(helper, []))

        local_calls = {
            callee
            for callee in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", body)
            if callee in defined_names and callee != name
        }
        direct_signals[name] = sigs
        call_graph[name] = local_calls

    resolved: Dict[str, Set[str]] = {}

    def resolve(name: str, visiting: Set[str]) -> Set[str]:
        if name in resolved:
            return resolved[name]
        if name in visiting:
            return set()

        visiting_next = set(visiting)
        visiting_next.add(name)

        out = set(direct_signals.get(name, set()))
        for callee in call_graph.get(name, set()):
            out.update(resolve(callee, visiting_next))

        resolved[name] = out
        return out

    return {name: sorted(resolve(name, set())) for name in direct_signals}


def parse_debug_mapping(tb_wrapper_sv: Path) -> Dict[str, str]:
    text = tb_wrapper_sv.read_text(encoding="utf-8", errors="replace")
    mapping: Dict[str, str] = {}
    for m in re.finditer(r"assign\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*dut\.([A-Za-z_][A-Za-z0-9_]*)\s*;", text):
        mapping[m.group(1)] = m.group(2)
    return mapping


def _exists_in_rtl(signal: str, rtl_text: str) -> bool:
    return re.search(rf"\b{re.escape(signal)}\b", rtl_text) is not None


def generate_matrix(
    reqs: List[Requirement],
    testplan_rows: List[TestplanRow],
    tc_signals: Dict[str, List[str]],
    dbg_map: Dict[str, str],
    rtl_text: str,
) -> Dict:
    req_links: Dict[str, List[TestplanRow]] = {}
    for row in testplan_rows:
        for rid in row.req_ids:
            req_links.setdefault(rid, []).append(row)

    req_order = [r.req_id for r in reqs]
    for rid in req_links.keys():
        if rid not in req_order:
            req_order.append(rid)

    req_text_map = {r.req_id: r.text for r in reqs}

    records = []
    for rid in req_order:
        linked = req_links.get(rid, [])

        test_ids = []
        tcs = []
        for row in linked:
            if row.test_id and row.test_id not in test_ids:
                test_ids.append(row.test_id)
            if row.testcase and row.testcase not in tcs:
                tcs.append(row.testcase)

        tb_sigs = set()
        rtl_sigs = set()
        missing_tc_impl = []

        for tc in tcs:
            sigs = tc_signals.get(tc)
            if sigs is None:
                missing_tc_impl.append(tc)
                continue
            for s in sigs:
                tb_sigs.add(s)
                mapped = dbg_map.get(s, s)
                if _exists_in_rtl(mapped, rtl_text):
                    rtl_sigs.add(mapped)

        if not linked:
            status = "NO_TESTPLAN"
        elif missing_tc_impl:
            status = "MISSING_TEST_IMPL"
        elif not rtl_sigs:
            status = "NO_SIGNAL_LINK"
        else:
            status = "OK"

        records.append(
            {
                "req_id": rid,
                "requirement": req_text_map.get(rid, ""),
                "test_ids": test_ids,
                "testcases": tcs,
                "tb_signals": sorted(tb_sigs),
                "rtl_signals": sorted(rtl_sigs),
                "missing_test_impl": missing_tc_impl,
                "status": status,
            }
        )

    testcase_records = []
    for row in testplan_rows:
        tc = row.testcase
        if not tc:
            continue
        sigs = tc_signals.get(tc, [])
        mapped = sorted(
            {
                dbg_map.get(s, s)
                for s in sigs
                if _exists_in_rtl(dbg_map.get(s, s), rtl_text)
            }
        )
        testcase_records.append(
            {
                "test_id": row.test_id,
                "testcase": tc,
                "req_ids": row.req_ids,
                "tb_signals": sigs,
                "rtl_signals": mapped,
                "implemented": tc in tc_signals,
            }
        )

    return {
        "schema_version": "trace_matrix/v1",
        "summary": {
            "requirements": len(records),
            "ok": sum(1 for r in records if r["status"] == "OK"),
            "no_testplan": sum(1 for r in records if r["status"] == "NO_TESTPLAN"),
            "missing_test_impl": sum(1 for r in records if r["status"] == "MISSING_TEST_IMPL"),
            "no_signal_link": sum(1 for r in records if r["status"] == "NO_SIGNAL_LINK"),
        },
        "requirements": records,
        "testcases": testcase_records,
        "debug_signal_map": dbg_map,
    }


def _md_join(items: List[str], max_len: int = 8) -> str:
    if not items:
        return "-"
    if len(items) <= max_len:
        return "<br>".join(items)
    return "<br>".join(items[:max_len]) + f"<br>...(+{len(items)-max_len})"


def to_markdown(data: Dict, reqs_file: str, testplan_file: str, test_file: str, rtl_file: str) -> str:
    lines: List[str] = []
    s = data["summary"]
    lines.append("# REQ -> Testcase -> RTL Signal Trace Matrix")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- reqs: `{reqs_file}`")
    lines.append(f"- testplan: `{testplan_file}`")
    lines.append(f"- tests: `{test_file}`")
    lines.append(f"- rtl: `{rtl_file}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- total requirements: {s['requirements']}")
    lines.append(f"- status OK: {s['ok']}")
    lines.append(f"- NO_TESTPLAN: {s['no_testplan']}")
    lines.append(f"- MISSING_TEST_IMPL: {s['missing_test_impl']}")
    lines.append(f"- NO_SIGNAL_LINK: {s['no_signal_link']}")
    lines.append("")
    lines.append("## Requirement Trace")
    lines.append("")
    lines.append("| REQ | Test IDs | Testcases | RTL Signals | Status |")
    lines.append("|---|---|---|---|---|")
    for r in data["requirements"]:
        lines.append(
            "| "
            + r["req_id"]
            + " | "
            + _md_join(r["test_ids"], 5)
            + " | "
            + _md_join(r["testcases"], 3)
            + " | "
            + _md_join(r["rtl_signals"], 6)
            + " | "
            + r["status"]
            + " |"
        )
    lines.append("")

    lines.append("## Testcase Signal Links")
    lines.append("")
    lines.append("| Test ID | Testcase | REQs | RTL Signals |")
    lines.append("|---|---|---|---|")
    seen = set()
    for t in data["testcases"]:
        key = (t["test_id"], t["testcase"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            "| "
            + (t["test_id"] or "-")
            + " | "
            + (t["testcase"] or "-")
            + " | "
            + _md_join(t["req_ids"], 6)
            + " | "
            + _md_join(t["rtl_signals"], 6)
            + " |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Signal links are auto-derived from `dut.<signal>` references in tests and debug mapping in tb wrapper.")
    lines.append("- A debug signal such as `debug_have_a` is mapped to DUT internal signal `have_a` via wrapper assignments.")
    lines.append("- This matrix is heuristic/static analysis; final truth remains simulation + verification report.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Generate REQ->Testcase->RTL trace matrix")
    p.add_argument("--reqs", required=True)
    p.add_argument("--testplan", required=True)
    p.add_argument("--tests", required=True)
    p.add_argument("--tb-py", default="", help="optional tb helper python file (auto-discover if empty)")
    p.add_argument("--tb-wrapper", required=True)
    p.add_argument("--rtl", required=True)
    p.add_argument("--out-md", required=True)
    p.add_argument("--out-json", required=True)
    p.add_argument("--dry-run", action="store_true", help="Do not write output files")
    p.add_argument("--strict", action="store_true", help="Fail if any requirement is not fully covered")
    args = p.parse_args()

    reqs_path = Path(args.reqs)
    testplan_path = Path(args.testplan)
    tests_path = Path(args.tests)
    tb_py_path = Path(args.tb_py) if args.tb_py else tests_path.parent.parent / "tb" / "ai_tb.py"
    tb_wrapper_path = Path(args.tb_wrapper)
    rtl_path = Path(args.rtl)

    for path in [reqs_path, testplan_path, tests_path, tb_wrapper_path, rtl_path]:
        if not path.exists():
            raise FileNotFoundError(f"Input not found: {path}")

    reqs = parse_requirements(reqs_path)
    rows = parse_testplan(testplan_path)
    tb_helper_sigs = parse_tb_helper_signals(tb_py_path) if tb_py_path.exists() else {}
    tc_sigs = parse_testcase_signals(tests_path, tb_helper_signals=tb_helper_sigs)
    dbg_map = parse_debug_mapping(tb_wrapper_path)
    rtl_text = rtl_path.read_text(encoding="utf-8", errors="replace")

    result = generate_matrix(reqs, rows, tc_sigs, dbg_map, rtl_text)

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)

    if not args.dry_run:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(
            to_markdown(result, args.reqs, args.testplan, args.tests, args.rtl) + "\n",
            encoding="utf-8",
        )
        print(f"[TRACE][OK] markdown: {out_md}")
        print(f"[TRACE][OK] json: {out_json}")
    else:
        print("[TRACE][DRY-RUN] No files written.")

    print(f"[TRACE][SUMMARY] {json.dumps(result['summary'], ensure_ascii=False)}")

    if args.strict:
        total = result["summary"]["requirements"]
        ok = result["summary"]["ok"]
        if ok < total:
            print(f"[TRACE][STRICT-FAIL] {total - ok} requirements not covered.")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
