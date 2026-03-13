# Incremental Handoff User Guide

## Purpose

This guide is for users who already have an upstream AI handoff and want to use OpenChipFlow in one of these two modes:

1. `handoff_intake`
   - inspect whether the handoff is complete enough
   - generate contract + semantic audit outputs
   - generate repair prompts for the upstream AI when the handoff is incomplete

2. `incremental_verify_ready`
   - consume a valid `verify_ready` handoff directly
   - run the existing downstream verification loop without regenerating RTL / TB

This is the user-facing companion to:

- [P0 plan](../env_dev/doc/incremental_artifact_handoff_p0_plan.md)
- [P1 intake plan](../env_dev/doc/handoff_intake_validator_p1_plan.md)
- [Prompt/materialize plan](../env_dev/doc/handoff_prompt_and_materialize_plan.md)

## Upstream AI Contract

Before running `handoff_intake`, generate and send the OpenChipFlow requirements prompt to the upstream AI:

```bash
python3 tools/generate_handoff_requirements_prompt.py --target-state verify_ready
```

The upstream AI must return a handoff bundle that follows this layout exactly:

```text
<handoff_root>/
  source_requirements/
    spec.md
    overview.md
    ...
  baseline_summary.md
  compat_constraints.md
  changed_files_allowlist.yaml
  spec.md
  reqs.md            # or delta_spec.md
  testplan.md        # or testplan_delta.md
  handoff_manifest.json   # required when the bundle is verify_ready
  rtl/...
  filelists/...
  tb/hdl/...
  tb/*.py
  tests/*.py
```

OpenChipFlow is strict about this layout. The design assets should not be spread across arbitrary folders.

## Mode 1: `handoff_intake`

### When To Use It

Use `handoff_intake` when the upstream AI gave you:

- a handoff directory with Markdown / YAML / JSON files
- a missing or uncertain manifest
- a partial handoff that needs one more feedback round

`handoff_intake` is now a mixed workflow:

- host-side contract audit + materialization
- optional AI semantic review against the original request/source docs

The outer runner still skips the top-level quota guard for `handoff_intake`; when semantic review is enabled, the workflow uses a stage-level quota gate right before the AI reviewer.

### Required Inputs

At minimum, provide one of:

- `--handoff-root <dir>`
- `--handoff-manifest <file>`

Recommended handoff files:

- `source_requirements/`
- `baseline_summary.md`
- `compat_constraints.md`
- `changed_files_allowlist.yaml`
- `spec.md`
- `reqs.md` or `delta_spec.md`
- `testplan.md` or `testplan_delta.md`
- `rtl/...`
- `filelists/...`
- `tb/hdl/...`
- `tb/*.py`
- `tests/*.py`

### Command Examples

Direct validator:

```bash
python3 tools/handoff_intake_validator.py \
  --workspace cocotb_ex \
  --handoff-root /path/to/handoff_dir \
  --source-requirements-root /path/to/handoff_dir/source_requirements \
  --semantic-review-mode required
```

Pipeline workflow:

```bash
python3 cocotb_ex/ai_cli_pipeline/run_pipeline.py \
  --workflow handoff_intake \
  --handoff-root ai_cli_pipeline/examples/incremental_manifestless
```

Runner entrypoint:

```bash
CHIPFLOW_HANDOFF_ROOT=/path/to/handoff_dir \
  ./chipflow run handoff_intake
```

Request manifest entrypoint:

```bash
./chipflow request \
  --request-manifest artifacts/protocol/examples/request_handoff_intake.json
```

### Outputs

All outputs are written under the current session:

- `cocotb_ex/artifacts/sessions/<session_id>/handoff/`
- `cocotb_ex/artifacts/sessions/<session_id>/workspace/`

- `handoff_requirements_prompt.txt`
  - static contract prompt to copy to the upstream AI before or after intake
- `handoff_source_index.json`
  - discovered `source_requirements/*` index
- `handoff_inventory.json`
  - scanned files and detected categories
- `handoff_audit.json`
  - machine-readable intake result
- `handoff_contract_audit.json`
  - contract-focused audit result used by the acceptance gate
- `handoff_gap_report.md`
  - human-readable pass/fail summary
- `handoff_repair_prompt.txt`
  - copy this content back to the upstream AI
- `handoff_contract_repair_prompt.txt`
  - contract/layout-specific upstream fix prompt
- `handoff_semantic_review_request.md`
  - generated when semantic review is enabled and the source context is available
- `handoff_semantic_review.json`
  - AI reviewer verdict
- `handoff_semantic_review.md`
  - human-readable semantic review
- `handoff_semantic_repair_prompt.txt`
  - targeted upstream fix prompt based on the semantic review
- `handoff_acceptance.json`
  - final acceptance result combining contract + semantic review
- `handoff_manifest.candidate.json`
  - generated only when the handoff is already complete enough to infer a valid `verify_ready` manifest
- `handoff_materialization.json`
  - source/destination/hash mapping for imported docs and design assets
- `handoff_manifest.materialized.json`
  - the manifest that points to the session workspace after automatic import/materialization

### How To Feed Back To The Upstream AI

1. Before running intake, send `handoff_requirements_prompt.txt` to the upstream AI and require the exact bundle layout shown above.
2. Run `handoff_intake`.
3. Open the session `handoff/` directory and inspect:
   - `handoff_contract_repair_prompt.txt`
   - `handoff_semantic_repair_prompt.txt` when semantic review ran
4. If the intake already passes, use `handoff_manifest.materialized.json` directly.
5. If the intake fails, paste the contract/semantic repair prompt into the upstream AI session.
6. Ask the upstream AI to update only the missing or weak handoff files.
7. Re-run `handoff_intake`.
8. When the audit passes, switch to `incremental_verify_ready` with the materialized manifest.

The repair prompt is deterministic and already contains:

- the current OpenChipFlow handoff contract
- the required `rtl/filelists/tb/tests` directory layout
- the currently detected files
- the missing categories
- the manifest fields required by OpenChipFlow
- the instruction to preserve already-good files

## Automatic Materialization

You no longer need to manually pre-place baseline RTL/TB/tests/filelist into the shared workspace.

`handoff_intake` now materializes:

- `spec.md` -> `workspace/ai_cli_pipeline/specs/out/spec.md`
- `reqs.md` -> `workspace/ai_cli_pipeline/specs/out/reqs.md`
- `testplan.md` -> `workspace/ai_cli_pipeline/specs/out/testplan.md`
- baseline/compat/allowlist docs -> `workspace/handoff/`
- `source_requirements/*` -> `handoff/source_context/source_requirements/*`
- design assets:
  - `rtl/...` -> `workspace/rtl/...`
  - `filelists/...` -> `workspace/filelists/...`
  - `tb/...` -> `workspace/tb/...`
  - `tests/...` -> `workspace/tests/...`

This creates a three-layer model:

1. immutable imported bundle
2. mutable session workspace
3. immutable run snapshot

## Mode 2: `incremental_verify_ready`

### When To Use It

Use `incremental_verify_ready` only when the handoff already has a valid `handoff_manifest.materialized.json` and the required design / verification assets have been imported into the session workspace.

### Required Inputs

A valid `artifact_handoff_manifest/v1` file is required.

The preferred input is:

- `cocotb_ex/artifacts/sessions/<session_id>/handoff/handoff_manifest.materialized.json`

The materialized manifest should point to:

- `spec_file`
- `reqs_file`
- `testplan_file`
- `baseline_summary_file`
- `compat_constraints_file`
- optional `allowlist_file`
- `rtl_file`
- `rtl_filelist`
- `tb_wrapper_file`
- `tb_py_file`
- `test_file`
- `top_level`
- `test_module`
- `smoke_testcase`

### Command Examples

Pipeline workflow:

```bash
python3 cocotb_ex/ai_cli_pipeline/run_pipeline.py \
  --workflow incremental_verify_ready \
  --handoff-manifest cocotb_ex/artifacts/sessions/<session_id>/handoff/handoff_manifest.materialized.json
```

Runner entrypoint:

```bash
CHIPFLOW_HANDOFF_MANIFEST=cocotb_ex/artifacts/sessions/<session_id>/handoff/handoff_manifest.materialized.json \
  ./chipflow run incremental_verify_ready
```

Request manifest entrypoint:

```bash
./chipflow request \
  --request-manifest artifacts/protocol/examples/request_incremental_verify_ready.json
```

### Outputs

The verification flow reuses the existing downstream stages and generates session-scoped outputs:

- `artifacts/sessions/<session_id>/handoff/handoff_context.json`
- `artifacts/sessions/<session_id>/workspace/artifacts/case_schedule.json`
- `artifacts/sessions/<session_id>/workspace/ai_cli_pipeline/verification/req_trace_matrix.md`
- `artifacts/sessions/<session_id>/workspace/ai_cli_pipeline/verification/req_trace_matrix.json`
- `artifacts/sessions/<session_id>/workspace/ai_cli_pipeline/verification/verify.md`
- `artifacts/runs/<run_id>/...`

## Practical Standard

### A Handoff Is `verify_ready` When

- the design intent is documented
- the compatibility boundaries are documented
- the patch scope is documented
- the manifest resolves inside the current pipeline workspace
- the RTL / filelist / TB / cocotb assets are all present
- the smoke testcase and test module are explicit

### A Handoff Is Not Yet `verify_ready` When

- it only contains analysis documents
- it lives outside the current workspace and no valid materialized manifest maps the files in
- filelist / TB / tests are still implicit
- the validator can only infer part of the design asset set

## Current Concurrency Limitation

Different repos are already isolated by `project_root`, so running OpenChipFlow in separate repos is acceptable.

The current implementation is not yet safe for concurrent mutable runs in the same repo because several pipeline outputs still use shared fixed paths, for example:

- `cocotb_ex/artifacts/handoff/*`
- `cocotb_ex/ai_cli_pipeline/verification/*`
- `cocotb_ex/artifacts/case_schedule.json`

Until per-run namespacing lands, use this rule:

- different repos: okay
- same repo, multiple dry-runs: usually okay
- same repo, multiple real mutable runs at the same time: not recommended

## Recommended User Flow

1. Start with `handoff_intake`.
2. If the audit fails, use `handoff_repair_prompt.txt` to drive one more upstream AI round.
3. If the audit passes, prefer `handoff_manifest.materialized.json`.
4. Run `incremental_verify_ready`.

For TUI or automation integration, prefer `./chipflow request --request-manifest ...` over ad hoc environment variables, because it preserves:

- `session_id`
- imported input file records
- `request.normalized.json`
- run-level `ui_manifest.json`
