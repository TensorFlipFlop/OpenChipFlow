# Runner Request Manifest Examples

These examples show the three supported `request manifest` modes:

- [`request_spec_flow.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/artifacts/protocol/examples/request_spec_flow.json)
  - import a spec file and run the original spec-driven flow
- [`request_handoff_intake.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/artifacts/protocol/examples/request_handoff_intake.json)
  - audit an upstream handoff
  - includes `source_requirements_root`
  - keeps `semantic_review_mode=off` so the example stays deterministic and quota-free
- [`request_incremental_verify_ready.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/artifacts/protocol/examples/request_incremental_verify_ready.json)
  - run a verify-ready handoff through the downstream verification loop

Use them with:

```bash
./chipflow request --request-manifest artifacts/protocol/examples/request_spec_flow.json
```

Preview without executing any step:

```bash
./chipflow request --request-manifest artifacts/protocol/examples/request_spec_flow.json --dry-run
```

Rules:

- `execution.mode` selects flow depth, for example `plan` vs `all`
- `execution.dry_run` or CLI `--dry-run` controls preview-only behavior
- real flow and dry-run are separate knobs; no stage should dry-run unless one of those dry-run switches is enabled

The input schema is defined in:

- [`runner_request_manifest.schema.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/config/schemas/runner_request_manifest.schema.json)

The execution result is summarized in:

- `artifacts/runs/<run_id>/ui_manifest.json`
