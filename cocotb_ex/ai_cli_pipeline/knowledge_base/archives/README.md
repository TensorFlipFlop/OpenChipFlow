# Failure Case Archives

This directory stores snapshots of failed verification cases that require human review or AI analysis to extract new patterns.

## Archive Structure

When a fix loop succeeds after failures, the pipeline should create a subdirectory here named:
`case_<timestamp>_<case_id>/`

### Contents
*   **`failure.log`**: The error log that triggered the fix loop.
*   **`fix_summary.md`**: The explanation provided by the Fixer agent.
*   **`code_diff.patch`**: The diff showing what changed in RTL/TB to fix the issue.

## Usage for Knowledge Engineering
A `knowledge_engineer` agent should periodically scan this directory:
1.  Read the `failure.log` and `fix_summary.md`.
2.  Extract the root cause (e.g., "Timer(0) usage").
3.  Update `../patterns/fix_patterns.json` or `../guidelines/*.md` with a generalized rule.
4.  (Optional) Move the processed case folder to a `processed/` subdirectory.
