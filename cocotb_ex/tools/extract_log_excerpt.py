#!/usr/bin/env python3
import argparse
import re
from pathlib import Path
from typing import List, Set, Tuple

def get_error_indices(lines: List[str], context: int) -> Set[int]:
    """Find line indices of errors and their context."""
    indices = set()
    # Case-insensitive search for "error"
    # We can refine this regex to be more specific if needed (e.g., r"\bERROR\b")
    error_pattern = re.compile(r"error", re.IGNORECASE)
    
    for i, line in enumerate(lines):
        if error_pattern.search(line):
            start = max(0, i - context)
            end = min(len(lines), i + context + 1)
            for idx in range(start, end):
                indices.add(idx)
    return indices

def get_tail_indices(total_lines: int, tail_count: int) -> Set[int]:
    """Get indices for the last N lines."""
    start = max(0, total_lines - tail_count)
    return set(range(start, total_lines))

def merge_indices(indices: Set[int]) -> List[Tuple[int, int]]:
    """Convert a set of indices into sorted, contiguous ranges."""
    if not indices:
        return []
    
    sorted_idx = sorted(list(indices))
    ranges = []
    
    if not sorted_idx:
        return []

    range_start = sorted_idx[0]
    current = sorted_idx[0]
    
    for idx in sorted_idx[1:]:
        if idx == current + 1:
            current = idx
        else:
            ranges.append((range_start, current))
            range_start = idx
            current = idx
    ranges.append((range_start, current))
    
    return ranges

def format_excerpt(lines: List[str], ranges: List[Tuple[int, int]]) -> str:
    """Format the lines based on ranges, adding skip markers."""
    output = []
    last_end = -1
    
    for start, end in ranges:
        # If there is a gap between the last range and this one
        if last_end != -1 and start > last_end + 1:
            skipped = start - (last_end + 1)
            output.append(f"\n... (skipped {skipped} lines) ...\n")
        elif last_end == -1 and start > 0:
             # Gap at the beginning
             output.append(f"... (skipped {start} lines) ...\n")
             
        # Add the lines for this range
        # end is inclusive in our ranges logic, but slice is exclusive
        output.extend(lines[start : end + 1])
        last_end = end
        
    return "\n".join(output)

def read_smart_excerpt(path: Path, tail_lines: int = 100, error_context: int = 10) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return f"Error reading file: {e}"

    if not content:
        return ""

    # 1. Identify key regions
    tail_idxs = get_tail_indices(len(content), tail_lines)
    error_idxs = get_error_indices(content, error_context)
    
    # 2. Merge all interesting lines
    all_idxs = tail_idxs.union(error_idxs)
    
    # 3. Create ranges
    ranges = merge_indices(all_idxs)
    
    # 4. Format output
    return format_excerpt(content, ranges)

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract smart log excerpt (Tail + Errors)")
    parser.add_argument("--input", required=True, help="Path to the log file")
    parser.add_argument("--tail", type=int, default=100, help="Number of lines to capture from the end")
    parser.add_argument("--context", type=int, default=10, help="Lines of context around 'error' matches")
    parser.add_argument("--output", help="Optional output file")
    args = parser.parse_args()

    log_path = Path(args.input)
    if not log_path.exists():
        # Fail gracefully if log doesn't exist (agent might be checking prematurely)
        print(f"Log file not found: {log_path}")
        return

    excerpt = read_smart_excerpt(log_path, args.tail, args.context)
    
    if args.output:
        Path(args.output).write_text(excerpt, encoding="utf-8")
    else:
        print(excerpt)

if __name__ == "__main__":
    main()