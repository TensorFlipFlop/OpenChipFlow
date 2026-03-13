import re
import subprocess
from pathlib import Path


CASE_RE = re.compile(r"\[case:([^\]]+)\]")
PERMIT_RE = re.compile(r"\[permit:([^\]]+)\]")


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def generate_pr_md(output_path: Path) -> None:
    log_output = _run_git(["log", "--pretty=format:%H%x09%s"])
    cases: dict[str, list[str]] = {}
    permits: dict[str, set[str]] = {}

    for line in log_output.splitlines():
        if "\t" not in line:
            continue
        _sha, subject = line.split("\t", 1)
        case_ids = CASE_RE.findall(subject)
        if not case_ids:
            continue
        for case_id in case_ids:
            cases.setdefault(case_id, []).append(subject)
            if "REFEREE-APPROVED" in subject:
                permits.setdefault(case_id, set()).update(PERMIT_RE.findall(subject))

    lines = ["## Summary"]
    if cases:
        lines.append(f"- Cases: {', '.join(sorted(cases))}")
    else:
        lines.append("- Cases: none detected")

    lines.append("\n## Cases")
    for case_id, subjects in sorted(cases.items()):
        lines.append(f"- {case_id}:")
        for subj in subjects:
            lines.append(f"  - {subj}")

    lines.append("\n## Permits")
    if permits:
        for case_id, permit_ids in sorted(permits.items()):
            if permit_ids:
                lines.append(f"- {case_id}: {', '.join(sorted(permit_ids))}")
            else:
                lines.append(f"- {case_id}: REFEREE-APPROVED (permit tag missing)")
    else:
        lines.append("- none")

    lines.append("\n## Test plan")
    lines.append("- [ ] add test commands here")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
