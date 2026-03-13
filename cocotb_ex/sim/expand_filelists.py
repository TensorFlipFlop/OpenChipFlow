#!/usr/bin/env python3
"""
Expand one or more RTL filelists.

Supported syntax (common VCS style):
  - Blank lines / comments (# or //) are ignored
  - "-f other.f", "-F other.f", or concatenated "-fother.f" includes another filelist (recursive)
  - Plain tokens are treated as source file paths
  - Option tokens starting with '+' or '-' (e.g. +incdir+, +define+, -y, -v) are collected as
    extra compile arguments

All relative paths are resolved w.r.t. the directory of the filelist that
contains them.

Usage:
  expand_filelists.py --sources <filelist...>   # output flat source list (abs paths)
  expand_filelists.py --args <filelist...>      # output extra compile args
"""

import argparse
import os
import sys
import traceback
from typing import Dict, List, Optional, Set, Tuple


def _strip_inline_comment(line: str) -> str:
    for sep in ("//", "#"):
        if sep in line:
            line = line.split(sep, 1)[0]
    return line.strip()


def _resolve_path(base_dir: str, tok: str) -> str:
    # Keep env/tilde based paths untouched to allow shell/VCS expansion.
    if tok.startswith(("$", "~")):
        return tok
    return tok if os.path.isabs(tok) else os.path.abspath(os.path.join(base_dir, tok))


def _normalize_incdir(base_dir: str, tok: str) -> str:
    # +incdir+dir1+dir2...
    prefix = "+incdir+"
    if not tok.startswith(prefix):
        return tok
    dirs = tok[len(prefix) :].split("+")
    abs_dirs = [_resolve_path(base_dir, d) for d in dirs if d]
    return prefix + "+".join(abs_dirs)


def _parse_filelist(
    path: str,
    seen_lists: Set[str],
    out_files: List[str],
    out_args: List[str],
    src_info: Dict[str, Tuple[str, str]],
) -> None:
    abs_path = os.path.abspath(path)
    if abs_path in seen_lists:
        return
    seen_lists.add(abs_path)

    base_dir = os.path.dirname(abs_path)
    with open(abs_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = _strip_inline_comment(raw.strip())
            if not line:
                continue

            parts = line.split()
            i = 0
            while i < len(parts):
                tok = parts[i]

                # include other filelists
                if tok in ("-f", "-F"):
                    i += 1
                    if i >= len(parts):
                        break
                    inc = parts[i]
                    _parse_filelist(
                        _resolve_path(base_dir, inc), seen_lists, out_files, out_args, src_info
                    )
                    i += 1
                    continue
                if tok.startswith(("-f", "-F")) and len(tok) > 2:
                    inc = tok[2:]
                    _parse_filelist(
                        _resolve_path(base_dir, inc), seen_lists, out_files, out_args, src_info
                    )
                    i += 1
                    continue

                # options -> extra args
                if tok.startswith("+"):
                    out_args.append(_normalize_incdir(base_dir, tok))
                    i += 1
                    continue
                if tok.startswith("-"):
                    # common options requiring a path argument
                    if tok in ("-y", "-v", "-incdir"):
                        out_args.append(tok)
                        i += 1
                        if i < len(parts):
                            out_args.append(_resolve_path(base_dir, parts[i]))
                        i += 1
                        continue
                    out_args.append(tok)
                    i += 1
                    continue

                # plain source file
                resolved = _resolve_path(base_dir, tok)
                out_files.append(resolved)
                src_info.setdefault(resolved, (tok, base_dir))
                i += 1


def _unique_preserve(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _expand(argv: List[str]) -> Tuple[List[str], List[str], Dict[str, Tuple[str, str]]]:
    out_files: List[str] = []
    out_args: List[str] = []
    seen_lists: Set[str] = set()
    src_info: Dict[str, Tuple[str, str]] = {}
    for fl in argv:
        _parse_filelist(fl, seen_lists, out_files, out_args, src_info)
    return _unique_preserve(out_files), _unique_preserve(out_args), src_info


def _hint_missing_source(
    missing_path: str, src_info: Dict[str, Tuple[str, str]]
) -> Optional[str]:
    info = src_info.get(missing_path)
    if not info:
        return None
    raw, base_dir = info
    if raw.startswith(("$", "~")) or os.path.isabs(raw):
        return None
    if raw.startswith(("../", "./")):
        return None
    if os.path.basename(base_dir) != "filelists":
        return None
    candidate = os.path.abspath(os.path.join(base_dir, "..", raw))
    if os.path.isfile(candidate):
        return f"filelist entry '{raw}' looks repo-root relative; try '../{raw}'"
    return None


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sources", action="store_true", help="print expanded source file list")
    group.add_argument("--args", action="store_true", help="print expanded compile args")
    parser.add_argument("--check", action="store_true", help="fail if expanded sources are missing")
    parser.add_argument("filelists", nargs="+", help="one or more filelist paths")
    ns = parser.parse_args(argv)

    try:
        sources, args, src_info = _expand(ns.filelists)
    except FileNotFoundError as exc:
        missing = exc.filename or str(exc)
        sys.stderr.write(f"[expand_filelists] ERROR: missing filelist: {missing}\n")
        sys.stderr.write("[expand_filelists] Hint: check RTL_FILELISTS and '-f' includes.\n")
        return 2
    except Exception:  # pragma: no cover
        sys.stderr.write("[expand_filelists] ERROR: unexpected exception while parsing filelists\n")
        sys.stderr.write(traceback.format_exc())
        return 3

    if ns.check:
        missing_sources = [
            s for s in sources if not s.startswith(("$", "~")) and not os.path.isfile(s)
        ]
        if missing_sources:
            for s in missing_sources:
                sys.stderr.write(f"[expand_filelists] MISSING source: {s}\n")
                hint = _hint_missing_source(s, src_info)
                if hint:
                    sys.stderr.write(f"[expand_filelists] HINT: {hint}\n")
            return 4

    if ns.args:
        sys.stdout.write(" ".join(args))
    else:
        sys.stdout.write(" ".join(sources))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
