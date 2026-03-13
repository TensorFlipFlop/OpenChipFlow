#!/usr/bin/env python3
import argparse
import base64
import fnmatch
import json
import os
import shlex
import subprocess
from pathlib import Path

if __package__ is None:
    import sys
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    import orchestrator.context_builder as context_builder
    from orchestrator.gitops import write_current_case, write_current_permit_id
    from orchestrator.hooks import collect_staged_tb3_files, generate_permit, write_regression_ok
    from orchestrator.prgen import generate_pr_md
    from orchestrator.router import CaseState, Router
    from orchestrator.triage import triage_log
else:
    from . import context_builder
    from .gitops import write_current_case, write_current_permit_id
    from .hooks import collect_staged_tb3_files, generate_permit, write_regression_ok
    from .prgen import generate_pr_md
    from .router import CaseState, Router
    from .triage import triage_log


def load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"PyYAML required to read {path}: {exc}") from exc
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "git rev-parse failed")
    return Path(result.stdout.strip())


def parse_cmd(cmd: str | list[str]) -> list[str]:
    return cmd if isinstance(cmd, list) else shlex.split(cmd)


def run_cmd(cmd: list[str], env: dict | None = None) -> int:
    result = subprocess.run(cmd, check=False, text=True, env=env)
    return result.returncode


def tb3_touched(policies: dict) -> bool:
    diff = subprocess.run(
        ["git", "diff", "--name-only"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if diff.returncode != 0:
        return False
    files = diff.stdout.splitlines()
    for level in policies.get("tb_levels", []):
        if level.get("name") != "TB3":
            continue
        for pattern in level.get("patterns", []) or []:
            if any(fnmatch.fnmatch(f, pattern) for f in files):
                return True
    return False


def blast_radius() -> tuple[int, int]:
    diff = subprocess.run(
        ["git", "diff", "--numstat"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if diff.returncode != 0:
        return 0, 0
    files_changed = 0
    loc_changed = 0
    for line in diff.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted = parts[0], parts[1]
        added_i = int(added) if added.isdigit() else 0
        deleted_i = int(deleted) if deleted.isdigit() else 0
        files_changed += 1
        loc_changed += added_i + deleted_i
    return files_changed, loc_changed


def case_loop(args: argparse.Namespace) -> int:
    root = repo_root()
    router_cfg = load_yaml(root / args.router)
    policies_cfg = load_yaml(root / args.policies)
    orch_cfg = load_yaml(root / args.orchestrator)

    router = Router(router_cfg)
    state = CaseState()
    case_id = args.case_id
    write_current_case(root / "cocotb_ex/artifacts/.current_case", case_id)

    log_dir = root / orch_cfg.get("paths", {}).get("log_dir", "cocotb_ex/artifacts/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    sim_cmd = parse_cmd(args.sim_cmd) if args.sim_cmd else orch_cfg.get("case_loop", {}).get("sim_cmd", [])
    fix_cmd = parse_cmd(args.fix_cmd) if args.fix_cmd else orch_cfg.get("case_loop", {}).get("fix_cmd", [])
    rerun_cmd = parse_cmd(args.rerun_cmd) if args.rerun_cmd else orch_cfg.get("case_loop", {}).get("rerun_cmd", [])
    max_retries = args.max_retries or orch_cfg.get("case_loop", {}).get("max_retries", 3)

    if not sim_cmd:
        raise SystemExit("sim_cmd is required for case loop")

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        log_path = log_dir / f"case_{case_id}_attempt{attempt}.log"
        env = os.environ.copy()
        env.update({"CASE": case_id, "SEED": str(args.seed), "SIM_LOG": str(log_path)})
        if args.toplevel:
            env["TOPLEVEL"] = args.toplevel
        if args.rtl_filelists:
            env["RTL_FILELISTS"] = args.rtl_filelists
        if args.test_module:
            env["COCOTB_TEST_MODULES"] = args.test_module
        if args.testcase:
            env["COCOTB_TESTCASE"] = args.testcase

        rc = run_cmd(sim_cmd, env=env)
        if rc == 0:
            return 0

        if not log_path.exists():
            fallback_log = root / "cocotb_ex/artifacts/logs" / f"cocotb_{case_id}_seed{args.seed}.log"
            if fallback_log.exists():
                log_path = fallback_log
            else:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(
                    f"[orchestrator] simulation failed with rc={rc}, but expected log was not generated.\n",
                    encoding="utf-8",
                )

        triage = triage_log(log_path, router_cfg)
        router.update_state(triage.error_class, state)

        files_changed, loc_changed = blast_radius()
        if router.should_escalate(
            triage.error_class,
            state,
            tb3_touched=tb3_touched(policies_cfg),
            blast_radius_files=files_changed,
            blast_radius_loc=loc_changed,
        ):
            context_builder.build_cleanroom_packet(
                case_id=case_id,
                job_id=f"case_{case_id}_attempt{attempt}",
                spec_ir_path=root / args.spec_ir,
                reqs_path=Path(args.reqs) if args.reqs else None,
                error_summary={
                    "error_class": triage.error_class,
                    "tool": args.tool,
                    "message": triage.message,
                    "log_excerpt": triage.excerpt,
                },
                repro_cmd=" ".join(sim_cmd),
                repro_params={"case_id": case_id, "seed": args.seed},
                taboo_list=args.taboo or [],
                policies_path=root / args.policies,
                output_path=root / args.cleanroom_out,
            )
            return 1

        if not fix_cmd:
            return 1

        fix_rc = run_cmd(fix_cmd, env=env)
        if fix_rc != 0:
            return fix_rc

        if rerun_cmd:
            rerun_rc = run_cmd(rerun_cmd, env=env)
            if rerun_rc == 0:
                return 0

    return 1


def cmd_triage(args: argparse.Namespace) -> int:
    router_cfg = load_yaml(repo_root() / args.router) if args.router else {}
    result = triage_log(Path(args.log), router_cfg)
    payload = {"error_class": result.error_class, "message": result.message, "excerpt": result.excerpt}
    print(json.dumps(payload, indent=2))
    return 0


def cmd_cleanroom(args: argparse.Namespace) -> int:
    root = repo_root()
    packet = context_builder.build_cleanroom_packet(
        case_id=args.case_id,
        job_id=args.job_id,
        spec_ir_path=root / args.spec_ir,
        reqs_path=Path(args.reqs) if args.reqs else None,
        error_summary={
            "error_class": args.error_class,
            "tool": args.tool,
            "message": args.message,
            "log_excerpt": Path(args.log).read_text(encoding="utf-8", errors="replace"),
        },
        repro_cmd=args.repro_cmd,
        repro_params=json.loads(args.repro_params) if args.repro_params else {},
        taboo_list=args.taboo or [],
        policies_path=root / args.policies,
        output_path=root / args.output,
    )
    print(json.dumps(packet, indent=2))
    return 0


def cmd_permit(args: argparse.Namespace) -> int:
    root = repo_root()
    policies = load_yaml(root / args.policies)
    tb3_patterns = []
    for level in policies.get("tb_levels", []):
        if level.get("name") == "TB3":
            tb3_patterns.extend(level.get("patterns", []) or [])
    tb3_paths = args.tb3_path or collect_staged_tb3_files(tb3_patterns)

    permit_path = generate_permit(
        case_id=args.case_id,
        tb3_paths=tb3_paths,
        permit_dir=root / args.permit_dir,
        key_file=root / args.key_file,
        referee_model=args.referee_model,
        required_regression=args.required_regression,
    )
    payload = {"permit_path": str(permit_path), "case_id": args.case_id}
    print(json.dumps(payload, indent=2))
    return 0


def _permit_id_from_file(path: Path) -> str:
    payload_b64 = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("payload_b64:"):
            payload_b64 = line.split(":", 1)[1].strip().strip('"')
            break
    if not payload_b64:
        return ""
    payload = json.loads(base64.b64decode(payload_b64).decode("utf-8", "ignore"))
    return payload.get("permit_id", "")


def cmd_regression_ok(args: argparse.Namespace) -> int:
    root = repo_root()
    permit_path = root / args.permit_dir / f"{args.case_id}.permit.yaml"
    permit_id = args.permit_id or _permit_id_from_file(permit_path)
    if not permit_id:
        raise SystemExit("permit_id not found; provide --permit-id or valid permit file")
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    ok_path = root / args.permit_dir / f"{args.case_id}.regression.ok"
    write_regression_ok(ok_path, permit_id, base_commit)
    write_current_permit_id(root / "cocotb_ex/artifacts/.current_permit_id", permit_id)
    print(json.dumps({"regression_ok": str(ok_path)}, indent=2))
    return 0


def cmd_prgen(args: argparse.Namespace) -> int:
    output_path = repo_root() / args.output
    generate_pr_md(output_path)
    print(f"Wrote {output_path}")
    return 0


def cmd_enable_hooks(args: argparse.Namespace) -> int:
    root = repo_root()
    hooks_cfg = load_yaml(root / args.hooks)
    hooks_path = hooks_cfg.get("hooks", {}).get("hooks_path")
    if not hooks_path:
        raise SystemExit("hooks_path missing from hooks.yaml")
    subprocess.run(["git", "config", "core.hooksPath", hooks_path], check=True)
    print(f"core.hooksPath set to {hooks_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="cocotb_ex orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    case_p = sub.add_parser("case", help="Run a single case loop")
    case_p.add_argument("--case-id", required=True)
    case_p.add_argument("--seed", default="1")
    case_p.add_argument("--sim-cmd")
    case_p.add_argument("--fix-cmd")
    case_p.add_argument("--rerun-cmd")
    case_p.add_argument("--max-retries", type=int)
    case_p.add_argument("--toplevel")
    case_p.add_argument("--rtl-filelists")
    case_p.add_argument("--test-module")
    case_p.add_argument("--testcase")
    case_p.add_argument("--spec-ir", default="cocotb_ex/artifacts/spec_ir.yaml")
    case_p.add_argument("--reqs")
    case_p.add_argument("--tool", default="cocotb")
    case_p.add_argument("--taboo", action="append")
    case_p.add_argument("--router", default="cocotb_ex/config/router.yaml")
    case_p.add_argument("--policies", default="cocotb_ex/config/policies.yaml")
    case_p.add_argument("--orchestrator", default="cocotb_ex/config/orchestrator.yaml")
    case_p.add_argument("--cleanroom-out", default="cocotb_ex/artifacts/handoff/escalation_packet.json")
    case_p.set_defaults(func=case_loop)

    triage_p = sub.add_parser("triage", help="Classify a log file")
    triage_p.add_argument("--log", required=True)
    triage_p.add_argument("--router")
    triage_p.set_defaults(func=cmd_triage)

    clean_p = sub.add_parser("cleanroom", help="Build escalation packet")
    clean_p.add_argument("--case-id", required=True)
    clean_p.add_argument("--job-id", required=True)
    clean_p.add_argument("--spec-ir", required=True)
    clean_p.add_argument("--reqs")
    clean_p.add_argument("--error-class", required=True)
    clean_p.add_argument("--tool", required=True)
    clean_p.add_argument("--message", required=True)
    clean_p.add_argument("--log", required=True)
    clean_p.add_argument("--repro-cmd", required=True)
    clean_p.add_argument("--repro-params")
    clean_p.add_argument("--taboo", action="append")
    clean_p.add_argument("--policies", default="cocotb_ex/config/policies.yaml")
    clean_p.add_argument("--output", default="cocotb_ex/artifacts/handoff/escalation_packet.json")
    clean_p.set_defaults(func=cmd_cleanroom)

    permit_p = sub.add_parser("permit", help="Generate permit token")
    permit_p.add_argument("--case-id", required=True)
    permit_p.add_argument("--referee-model", default="Referee")
    permit_p.add_argument("--required-regression", action="append", default=[])
    permit_p.add_argument("--tb3-path", action="append")
    permit_p.add_argument("--permit-dir", default="cocotb_ex/artifacts/referee/permits")
    permit_p.add_argument("--key-file", default="cocotb_ex/.orchestrator/permit_hmac_key")
    permit_p.add_argument("--policies", default="cocotb_ex/config/policies.yaml")
    permit_p.set_defaults(func=cmd_permit)

    reg_p = sub.add_parser("regression-ok", help="Write regression marker")
    reg_p.add_argument("--case-id", required=True)
    reg_p.add_argument("--permit-id")
    reg_p.add_argument("--permit-dir", default="cocotb_ex/artifacts/referee/permits")
    reg_p.set_defaults(func=cmd_regression_ok)

    pr_p = sub.add_parser("prgen", help="Generate PR.md")
    pr_p.add_argument("--output", default="cocotb_ex/artifacts/pr/PR.md")
    pr_p.set_defaults(func=cmd_prgen)

    hook_p = sub.add_parser("enable-hooks", help="Enable repo hooks path")
    hook_p.add_argument("--hooks", default="cocotb_ex/config/hooks.yaml")
    hook_p.set_defaults(func=cmd_enable_hooks)

    args = parser.parse_args()
    exit_code = args.func(args)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
