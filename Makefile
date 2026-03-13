# Verilog Sim Template Automation Makefile
# Standardizes entry points for AI Agents and CI/CD pipelines.

PYTHON := python3
PIPELINE_SCRIPT := cocotb_ex/ai_cli_pipeline/run_pipeline.py
ORCHESTRATOR_SCRIPT := cocotb_ex/orchestrator/run.py

.PHONY: help all pipeline plan implement step verify sim format lint debug clean runner runner-plan runner-all runner-stage tui tui-smoke tui-go tui-go-smoke doctor-plus preflight pr-open run-registry triage-latest sticky-decision handoff-pack trace-matrix trace-gate schema-gate run-bundle run-retention run-retention-apply health-report implement-contract-gate

help:
	@echo "Available targets:"
	@echo "  all       - Run Plan then Implement phases sequentially"
	@echo "  pipeline  - Run the full AI automation pipeline (Spec -> RTL -> TB -> Sim)"
	@echo "  plan      - Run the Planning Phase (Spec -> Plan -> Refine -> Final Plan)"
	@echo "  implement - Run the Implementation Phase (RTL -> TB -> Sim -> Verify)"
	@echo "  step      - Run a single pipeline step (Usage: make step STEP=role_name)"
	@echo "  verify    - Run the verification orchestrator (Sim -> Triage -> Fix -> Cleanroom)"
	@echo "  sim       - Manual simulation via cocotb_ex/sim/Makefile (Legacy/Dev mode)"
	@echo "  format    - Format SystemVerilog code using Verible"
	@echo "  lint      - Lint SystemVerilog code using Verible"
	@echo "  debug     - Dry-run the pipeline to verify configuration and flow"
	@echo "  clean     - Archive all results to archive/ and cleanup all temporary files"
	@echo "  runner-*  - Opencode-style runner entry (run/stage/list)"
	@echo "  tui       - Launch terminal TUI (Python opencode-like)"
	@echo "  tui-smoke - Headless smoke validation for Python TUI"
	@echo "  tui-go    - Launch Go BubbleTea TUI"
	@echo "  tui-go-smoke - Headless smoke validation for Go TUI"	@echo "  doctor-plus - Extended host readiness check + JSON report"
	@echo "  preflight   - Workflow-based prerequisite check (WF=all|plan|implement|regress|pr)"
	@echo "  pr-open     - Resilient Gitee PR create wrapper (TITLE=... BODY=... BASE=... HEAD=...)"
	@echo "  run-registry - Build run manifest from latest .runner_logs"
	@echo "  triage-latest - Classify latest failed logs to normalized error classes"
	@echo "  sticky-decision - Decide STICKY_FIX vs ESCALATE based on triage trends"
	@echo "  handoff-pack - Build cleanroom escalation packet for high-tier fixer"
	@echo "  trace-matrix - Auto-generate REQ->Testcase->RTL signal trace matrix (md+json)"
	@echo "  trace-gate   - Enforce strict CI gate on req_trace_matrix.json"
	@echo "  schema-gate  - Validate trace matrix / run manifest JSON structures (fail-closed)"
	@echo "  run-bundle   - Snapshot run-level I/O bundle under artifacts/runs/<run_id>"
	@echo "  run-retention - Dry-run retention plan (keep latest N + milestone runs)"
	@echo "  run-retention-apply - Apply retention deletion plan"
	@echo "  health-report - Generate periodic pipeline health report (JSON+MD)"
	@echo "  implement-contract-gate - Enforce implement workflow must-call roles + required artifacts"

# Run Plan then Implement phases sequentially
all:
	$(MAKE) plan
	$(MAKE) implement

# Run the full end-to-end AI pipeline
# Automatically triggers clean (backup + reset) to ensure a clean slate.
pipeline: clean
	$(PYTHON) $(PIPELINE_SCRIPT)

# Run the Planning Phase (Spec -> Plan -> Refine -> Final Plan)
plan: clean
	$(PYTHON) $(PIPELINE_SCRIPT) --workflow plan

# Run the Implementation Phase (RTL -> TB -> Sim -> Verify)
implement:
	$(PYTHON) $(PIPELINE_SCRIPT) --workflow implement

# Run a single step manually
# Usage: make step STEP=spec_normalizer
step:
	@if [ -z "$(STEP)" ]; then echo "Error: STEP is undefined. Usage: make step STEP=role_name"; exit 1; fi
	$(PYTHON) $(PIPELINE_SCRIPT) --role $(STEP)

# Debug/Dry-run mode
debug:
	-$(PYTHON) cocotb_ex/ai_cli_pipeline/check_env.py
	$(PYTHON) $(PIPELINE_SCRIPT) --dry-run

# Archive results and cleanup all temp artifacts
clean:
	@echo "Archiving current artifacts before cleaning..."
	bash ./archive_and_clean.sh
	@echo "Cleaning AI pipeline temp outputs..."
	rm -f cocotb_ex/ai_cli_pipeline/verification/sim_fail.log
	rm -f cocotb_ex/ai_cli_pipeline/verification/regress_fail.log
	rm -f cocotb_ex/artifacts/.current_case cocotb_ex/artifacts/.current_permit_id
	rm -f cocotb_ex/.orchestrator/permit_hmac_key
	$(MAKE) -C cocotb_ex/sim clean_artifacts

# Run the Verification Orchestrator directly (Case Loop)
# Usage: make verify CASE=case_id
CASE ?= manual_run
verify:
	$(PYTHON) $(ORCHESTRATOR_SCRIPT) case \
		--case-id "$(CASE)" \
		--sim-cmd "bash cocotb_ex/tools/run_cocotb.sh" \
		--toplevel "ai_tb_top" \
		--rtl-filelists "../filelists/ai_dut.f" \
		--test-module "tests.test_ai" \
		--testcase "run_basic" \
		--max-retries 1

# Manual simulation entry point (Developer focused)
sim:
	$(MAKE) -C cocotb_ex/sim sim

# Format SystemVerilog code
format:
	bash cocotb_ex/tools/verible_format.sh

# Lint SystemVerilog code
lint:
	bash cocotb_ex/tools/run_verible.sh

runner:
	python3 scripts/runner.py plan

runner-plan:
	python3 scripts/runner.py run plan

runner-all:
	python3 scripts/runner.py run all

runner-stage:
	@if [ -z "$(STAGE)" ]; then echo "Error: STAGE is undefined. Usage: make runner-stage STAGE=verify"; exit 1; fi
	python3 scripts/runner.py stage $(STAGE)

tui:
	./chipflow-tui

tui-smoke:
	./chipflow-tui --smoke-test

tui-go:
	./chipflow-tui-go

tui-go-smoke:
	python3 tools/go_tui_smoke.py

doctor-plus:
	python3 tools/doctor_plus.py

WF ?= all
preflight:
	python3 tools/preflight_matrix.py --workflow $(WF)

BASE ?= master
HEAD ?= $(shell git branch --show-current)
BODY ?=
pr-open:
	@if [ -z "$(TITLE)" ]; then echo "Error: TITLE is required. Usage: make pr-open TITLE='...'( BODY=path/to/body.md )"; exit 1; fi
	@if [ -n "$(BODY)" ]; then \
		bash tools/pr_submit.sh -t "$(TITLE)" -B "$(BASE)" -H "$(HEAD)" -b "$(BODY)"; \
	else \
		bash tools/pr_submit.sh -t "$(TITLE)" -B "$(BASE)" -H "$(HEAD)"; \
	fi

run-registry:
	python3 tools/run_registry.py

triage-latest:
	python3 tools/triage_classify.py

CASE_ID ?= default
sticky-decision:
	python3 tools/sticky_fix_decider.py --case-id "$(CASE_ID)"

handoff-pack:
	python3 tools/escalation_packet.py --case-id "$(CASE_ID)"

trace-matrix:
	python3 cocotb_ex/tools/generate_trace_matrix.py \
		--reqs cocotb_ex/ai_cli_pipeline/specs/out/reqs.md \
		--testplan cocotb_ex/ai_cli_pipeline/specs/out/testplan.md \
		--tests cocotb_ex/tests/test_ai.py \
		--tb-wrapper cocotb_ex/tb/hdl/ai_tb_top.sv \
		--rtl cocotb_ex/rtl/ai_dut.sv \
		--out-md cocotb_ex/ai_cli_pipeline/verification/req_trace_matrix.md \
		--out-json cocotb_ex/ai_cli_pipeline/verification/req_trace_matrix.json

MIN_OK_RATE ?= 1.0
trace-gate:
	python3 cocotb_ex/tools/trace_matrix_gate.py \
		--input cocotb_ex/ai_cli_pipeline/verification/req_trace_matrix.json \
		--max-no-testplan 0 \
		--max-missing-test-impl 0 \
		--max-no-signal-link 0 \
		--min-ok-rate $(MIN_OK_RATE)

TRACE_JSON ?= cocotb_ex/ai_cli_pipeline/verification/req_trace_matrix.json
MANIFEST_JSON ?= cocotb_ex/artifacts/runs/$(RUN_ID)/manifest.json
schema-gate:
	python3 cocotb_ex/tools/schema_gate.py \
		--input $(TRACE_JSON) \
		--schema cocotb_ex/config/schemas/trace_matrix.schema.json \
		--label trace-matrix
	python3 cocotb_ex/tools/schema_gate.py \
		--input $(MANIFEST_JSON) \
		--schema cocotb_ex/config/schemas/run_manifest.schema.json \
		--label run-manifest

RUN_ID ?= manual_$(shell date +%Y%m%d_%H%M%S)
run-bundle:
	python3 cocotb_ex/tools/materialize_run_bundle.py \
		--workspace cocotb_ex \
		--run-id $(RUN_ID) \
		--out-root artifacts/runs \
		--inbox-spec ai_cli_pipeline/specs/inbox/spec.md \
		--spec ai_cli_pipeline/specs/out/spec.md \
		--reqs ai_cli_pipeline/specs/out/reqs.md \
		--testplan ai_cli_pipeline/specs/out/testplan.md \
		--rtl rtl/ai_dut.sv \
		--tb-wrapper tb/hdl/ai_tb_top.sv \
		--tb-py tb/ai_tb.py \
		--tests tests/test_ai.py \
		--verify-report ai_cli_pipeline/verification/verify.md \
		--trace-md ai_cli_pipeline/verification/req_trace_matrix.md \
		--trace-json ai_cli_pipeline/verification/req_trace_matrix.json

KEEP_LATEST ?= 10
MILESTONE_FILE ?= artifacts/runs/milestones.txt
run-retention:
	python3 tools/run_retention.py \
		--runs-root artifacts/runs \
		--keep-latest $(KEEP_LATEST) \
		--milestone-file $(MILESTONE_FILE) \
		--out artifacts/ops/retention_plan_$(shell date +%Y%m%d_%H%M%S).json

run-retention-apply:
	python3 tools/run_retention.py \
		--runs-root artifacts/runs \
		--keep-latest $(KEEP_LATEST) \
		--milestone-file $(MILESTONE_FILE) \
		--apply \
		--out artifacts/ops/retention_apply_$(shell date +%Y%m%d_%H%M%S).json

WINDOW_DAYS ?= 7
health-report:
	python3 tools/pipeline_health_report.py \
		--runs-root artifacts/runs \
		--triage-root artifacts/triage \
		--sticky-root artifacts/sticky \
		--window-days $(WINDOW_DAYS)

TS ?= $(shell date +%Y%m%d_%H%M)
implement-contract-gate:
	python3 tools/must_call_gate.py \
		--contract config/implement_contract.json \
		--workspace cocotb_ex \
		--log-dir ai_cli_pipeline/logs \
		--workflow implement \
		--timestamp $(TS) \
		--out ../artifacts/ops/implement_contract_$(TS).json
