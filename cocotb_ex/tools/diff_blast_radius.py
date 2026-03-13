#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "git command failed")
    return result.stdout


def parse_numstat(output: str) -> dict:
    files = []
    added_total = 0
    deleted_total = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], parts[2]
        added_i = int(added) if added.isdigit() else 0
        deleted_i = int(deleted) if deleted.isdigit() else 0
        files.append(path)
        added_total += added_i
        deleted_total += deleted_i
    return {
        "files_changed": len(files),
        "loc_added": added_total,
        "loc_deleted": deleted_total,
        "loc_changed": added_total + deleted_total,
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute diff blast radius")
    parser.add_argument("--base", default="HEAD", help="Base commit for diff")
    parser.add_argument("--head", help="Head commit for diff (optional)")
    parser.add_argument("--staged", action="store_true", help="Use staged diff against base")
    parser.add_argument("--paths", nargs="*", default=[], help="Restrict diff to paths")
    parser.add_argument("--output", help="Write JSON output to file")
    args = parser.parse_args()

    diff_args = ["diff", "--numstat"]
    if args.staged:
        diff_args.append("--cached")
    diff_args.append(args.base)
    if args.head:
        diff_args.append(args.head)
    if args.paths:
        diff_args.append("--")
        diff_args.extend(args.paths)

    output = run_git(diff_args)
    data = parse_numstat(output)

    if args.output:
        Path(args.output).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
