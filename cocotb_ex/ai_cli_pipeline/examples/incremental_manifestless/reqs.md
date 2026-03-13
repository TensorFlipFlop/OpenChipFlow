# Incremental AI DUT Requirements

## Required Behavior

- the handoff must be `verify_ready`
- the downstream workflow must consume existing RTL, filelist, TB wrapper, TB Python, and cocotb test files
- the handoff must document compatibility and patch boundaries

## Out Of Scope

- greenfield RTL regeneration
- broad directory rewrites
- renaming design files

## Acceptance

- the intake validator can infer a candidate manifest
- the downstream incremental verification workflow can reuse the existing assets
