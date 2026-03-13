# AI-Driven Verification Pipeline (cocotb_ex)

An automated, role-based pipeline that orchestrates AI agents (Claude, Codex, Gemini) to transform a design specification into a verified RTL implementation with a complete testbench.

## 🚀 Zero to Hero: Quick Start

### 1. Check Your Environment
Run the included doctor script to ensure you have the necessary tools (Python, Verilator, AI CLIs, API Keys).

```bash
python3 check_env.py
```

### 2. Prepare Your Spec
Place your design requirements in `specs/inbox/spec.md`.

```bash
cp my_design_spec.md specs/inbox/spec.md
```

### 3. Run the Pipeline
Launch the full automation flow.

```bash
python3 run_pipeline.py
```

---

## 🏗 Architecture & Roles

To ensure quality and prevent "cheating" (where AI generates tests that pass only because they match the buggy RTL), this pipeline separates concerns:

| Role | Agent (Default) | Responsibility |
| :--- | :--- | :--- |
| **Spec Normalizer** | Claude | Standardizes the input `spec.md` into a clean format. |
| **Reqs/Testplan Gen** | Codex | Derives granular Requirements and Test Plan. |
| **DE Agent** | Gemini | **Design Engineer**. Implements *only* the RTL (DUT). |
| **DV Agent** | Codex | **Verification Engineer**. Implements *only* the Testbench (TB) based on Testplan. |
| **Syntax Checker** | Host | Runs `verible` (SystemVerilog) and `python -m py_compile` to catch syntax errors early. |
| **Sim Runner** | Host | Runs `make sim` (Smoke Test). Triggers **Fix Loop** on failure. |
| **Verifier** | Claude | Analyzes simulation results/waveforms against the Spec. |
| **Regress Runner** | Host | Runs `make regress` (Full Regression). Triggers **Fix Loop** on failure. |
| **PR Submit** | Claude | Prepares a Git branch and submits a PR. |

---

## ⚙️ Configuration

The pipeline is highly configurable via `config.json` and local overrides.

### `config.json` (Shared Project Defaults)
Defines the standard tool mapping (e.g., using Docker), execution order, and role parameters.

### `config.local.json` (Local Overrides)
**Recommended:** Create this file to adapt to your specific machine (e.g., if you don't have Docker or want to swap AI models). This file is git-ignored.

**Example: Host-only execution with modified roles**
```json
{
  "ai_cli_tools": {
    "claude": { "runner": "host", "env": ["ANTHROPIC_API_KEY"] },
    "codex": { "runner": "host", "env": ["OPENAI_API_KEY"] },
    "gemini": { "runner": "host", "env": ["GEMINI_API_KEY"] }
  },
  "roles": {
    "req_testplan_generator": { "ai_cli": "claude" },
    "dv_agent": { "ai_cli": "claude" }
  },
  "global_parameters": {
    "default_timeout": 1200
  }
}
```

### Configurable Options

*   **`timeout`**: Maximum execution time (in seconds) for a role. Default: 600s (10 mins).
    *   Set globally via `"global_parameters": { "default_timeout": 600 }`.
    *   Set per-role via `"timeout": 1200`.
*   **`fix_loop_config`**: Controls the auto-fix retry logic.
    *   `max_retries`: Number of fix attempts (Default: 3 or 5).
    *   `fixer_role`: The AI role used to analyze logs and apply fixes.
    *   `rerun_role`: The task to run to verify the fix.

---

## 🛠 Commands & Usage

### Full Run
```bash
python3 run_pipeline.py
```

### Run Specific Role
Useful for debugging or resuming.
```bash
python3 run_pipeline.py --role regress_runner
```

### Dry Run
Print the commands without executing them.
```bash
python3 run_pipeline.py --dry-run
```

### Incremental Artifact-First Flow
Consume an upstream AI handoff directly, without rerunning `de_agent` / `dv_agent`.

User guide:

- `../docs/incremental_handoff_user_guide.md`

Example:
```bash
python3 run_pipeline.py \
  --workflow incremental_verify_ready \
  --handoff-manifest ai_cli_pipeline/examples/incremental_ai_dut/handoff_manifest.json \
  --dry-run
```

Runner entrypoint:
```bash
CHIPFLOW_HANDOFF_MANIFEST=cocotb_ex/ai_cli_pipeline/examples/incremental_ai_dut/handoff_manifest.json \
  ./chipflow run incremental_verify_ready --dry-run
```

Request manifest entrypoint:
```bash
./chipflow request \
  --request-manifest artifacts/protocol/examples/request_incremental_verify_ready.json
```

P0 expects a `verify_ready` handoff that already contains:

- `spec.md`, `reqs.md`, `testplan.md`
- existing RTL / filelist / TB / cocotb tests
- compatibility and patch-scope metadata

The checked-in example lives under:

- `ai_cli_pipeline/examples/incremental_ai_dut/`

### Handoff Intake Audit
Audit a raw handoff folder before trying to enter the verification workflow.

Example:
```bash
python3 run_pipeline.py \
  --workflow handoff_intake \
  --handoff-root ai_cli_pipeline/examples/incremental_manifestless
```

Runner entrypoint:
```bash
CHIPFLOW_HANDOFF_ROOT=cocotb_ex/ai_cli_pipeline/examples/incremental_manifestless \
  ./chipflow run handoff_intake
```

Request manifest entrypoint:
```bash
./chipflow request \
  --request-manifest artifacts/protocol/examples/request_handoff_intake.json
```

Outputs are written under `artifacts/handoff/`:

- `handoff_requirements_prompt.txt`
- `handoff_source_index.json`
- `handoff_inventory.json`
- `handoff_audit.json`
- `handoff_contract_audit.json`
- `handoff_gap_report.md`
- `handoff_repair_prompt.txt`
- `handoff_contract_repair_prompt.txt`
- `handoff_semantic_review_request.md` when semantic review is enabled and source context is available
- `handoff_semantic_review.json`
- `handoff_semantic_review.md`
- `handoff_semantic_repair_prompt.txt`
- `handoff_acceptance.json`
- `handoff_manifest.candidate.json` when the intake is complete enough to infer a manifest
- `handoff_materialization.json`
- `handoff_manifest.materialized.json`

Use this stage when:

- the upstream AI only produced Markdown / YAML files
- the manifest is missing or may be malformed
- you want deterministic contract feedback and, when source context is present, AI semantic feedback before asking the upstream AI to revise the handoff

Recommended upstream handoff layout:

- `source_requirements/...`
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

When `--session-root` is supplied, intake will also materialize these docs and design assets into:

- `artifacts/sessions/<session_id>/workspace/...`

and emit:

- `artifacts/sessions/<session_id>/handoff/handoff_manifest.materialized.json`

### Spec-Driven Request Manifest
When you want a TUI-safe, file-explicit entry for the original spec-driven flow, use:

```bash
./chipflow request \
  --request-manifest artifacts/protocol/examples/request_spec_flow.json
```

This avoids overwriting the shared `specs/inbox/spec.md` and writes the imported request inputs under the per-session directory.

Semantics:

- `execution.mode = plan | all` selects the real spec-driven flow depth
- `dry_run` is a separate preview switch; only explicit `--dry-run` or `execution.dry_run=true` should force preview mode

---

## 🔧 Troubleshooting

### "Fix Loop" Strategy (Anti-Verification Escape)
If simulation fails, the pipeline enters a fix loop. The `fixer` prompt is explicitly instructed to:
1.  **Prioritize fixing the DUT RTL.**
2.  **Assume the Testbench is correct** (unless there is a clear syntax/logic error).
3.  **NEVER remove assertions** to force a pass.

### Logs
*   **Pipeline Logs:** `ai_cli_pipeline/logs/<role>.log` (captures stdout/stderr of the AI tool).
*   **Simulation Logs:** `ai_cli_pipeline/verification/sim_fail.log` or `regress_fail.log`.
*   **Trace Matrix:** `ai_cli_pipeline/verification/req_trace_matrix.md` and `req_trace_matrix.json`.

### Traceability Matrix (Auto-Generated)
Generate requirement-to-testcase-to-RTL trace links:
```bash
make trace-matrix
```

Enforce strict quality gate (CI-friendly):
```bash
make trace-gate
```

Enforce JSON schema gate (fail-closed, for trace matrix + run manifest):
```bash
make schema-gate RUN_ID=manual_20260218_1500
```

### Run-Level Snapshot Bundle (Recommended)
Materialize a reproducible run bundle under `artifacts/runs/<run_id>/`:
```bash
make run-bundle RUN_ID=manual_20260218_1500
```

This captures input/derived/output/verification files separately, so `latest` and `run-history` views are both preserved.

### Common Issues
1.  **Timeout:** If `regress_runner` times out, increase `"default_timeout"` in `config.local.json`.
2.  **Docker Issues:** If Docker fails (e.g. network), verify `check_env.py` passes and consider using `"runner": "host"` in `config.local.json`.
