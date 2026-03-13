# Incremental AI DUT Compatibility Constraints

## Preserve

- preserve the `ai_tb_top` top-level wrapper
- preserve the `tests.test_ai` module import path
- preserve the filelist location expected by the simulator

## Must Not Change

- do not rename design files
- do not delete design files
- do not regenerate the whole design directory

## Allowable Scope

- only modify files declared in the allowlist
- keep new behavior compatible with the existing smoke and regression entrypoints
