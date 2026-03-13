# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/claude-code) when working with code in this repository.

## Repository Purpose

This repository contains Verilog/cocotb simulation templates with two main environments:
- **cocotb_vcs/** - Synopsys VCS/Verdi template for offline/enterprise environments (primary target for deployment)
- **cocotb_ex/** - Open-source counterpart using Verilator/GTKWave (for external development/testing)

Both templates share the same `rtl/`, `tb/`, `tests/`, and `filelists/` structure. Only the `sim/` directory differs to accommodate different toolchains.

## Directory Structure

```
verilog_sim_template/
├── cocotb_vcs/           # VCS/Verdi version (for offline/enterprise)
│   ├── cfg_env.csh       # Environment setup script (csh/tcsh)
│   ├── rtl/              # DUT RTL code (shared with cocotb_ex)
│   ├── tb/               # Reusable Python testbench + HDL wrappers
│   │   ├── *.py          # Python testbench classes (driver/monitor/scoreboard)
│   │   └── hdl/          # HDL wrappers (tb_*.sv)
│   ├── tests/            # Concrete test cases (@cocotb.test())
│   ├── filelists/        # RTL file lists
│   └── sim/              # Simulation entry point (Makefile, scripts)
│
├── cocotb_ex/            # Verilator version (open-source dev)
│   └── [same structure as cocotb_vcs/]
│
├── cocotb_offline/       # Offline Python dependencies
│   └── wheels_p12/       # Python 3.12 wheels for offline installation
│       ├── *.whl
│       └── README.md
│
└── tools/                # Local Python installation (3.12.7)
```

## Key Architecture Concepts

### Four-Component Model

The template uses a modular approach where DUT, TOP, TB, and case are independently swappable:

1. **DUT** - RTL code in `rtl/` with filelists in `filelists/*.f`
2. **TOP** - HDL wrapper in `tb/hdl/tb_<name>.sv` that instantiates DUT and provides clocks/reset
3. **TB** - Reusable Python testbench in `tb/*.py` (driver/monitor/scoreboard)
4. **Case** - Concrete tests in `tests/test_*.py` using `@cocotb.test()` decorator

### Variable Naming Conventions

- **COCOTB_TEST_MODULES** - Current cocotb test module (preferred in cocotb 2.x)
- **MODULE** - Legacy variable (mapped to COCOTB_TEST_MODULES if COCOTB_TEST_MODULES not set)
- **COCOTB_TESTCASE** - Specific test case function (preferred)
- **TESTCASE** - Legacy variable (mapped to COCOTB_TESTCASE if not set)
- **CASE** - Output directory naming (derived from TOPLEVEL/MODULE/TESTCASE)
- **TOPLEVEL** - HDL wrapper module name
- **RTL_FILELISTS** - Space-separated list of filelist files

### Output Directory Structure

```
sim/out/
└── <CASE>/                    # Per test configuration
    ├── seed<SEED>/            # Per simulation run
    │   ├── results.xml
    │   ├── waves.fsdb (VCS) / waves.vcd (Verilator)
    │   └── coverage.dat (Verilator)
    └── cov/
        ├── cm.vdb (VCS)
        └── cov_html/
```

## Common Commands

### cocotb_vcs (VCS/Verdi)

Environment setup (csh/tcsh only):
```csh
cd cocotb_vcs
source cfg_env.csh
cd sim
```

Basic simulation:
```csh
make                          # Run default test
make doctor                   # Environment check
make WAVES=0                  # Faster (no waveform)
make clean                    # Clean build artifacts
make distclean                # Clean everything including out/
```

Specify DUT/test:
```csh
make TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f \
  MODULE=tests.test_fifo TESTCASE=run_fifo_smoke SEED=1
```

Regression:
```csh
make regress REGR_MODULES="tests.test_fifo" REGR_SEEDS="1 2 3"
make suite                    # Built-in test suite (2 TOP × 2 case × multiple seeds)
```

View waveform:
```csh
make verdi                    # Open FSDB in Verdi
```

Coverage report:
```csh
make cov                      # Generate HTML coverage report
```

### cocotb_ex (Verilator)

```bash
cd cocotb_ex/sim
make                          # Run default test
make doctor                   # Environment check
make PYTHON_BIN=/path/to/python3.12
make gtkwave CASE=<CASE> SEED=<SEED>  # Open VCD in GTKWave
make cov CASE=<CASE>          # Generate coverage report
```

## Offline Python Dependencies

The target environment (cocotb_vcs) assumes no internet access. Python dependencies are pre-packaged in `cocotb_offline/wheels_p12/`.

### Installing from wheelhouse

```bash
# Minimal installation
python -m pip install --no-index --find-links /path/to/cocotb_offline/wheels_p12 \
  cocotb==2.0.1 cocotb-bus==0.3.0 cocotb-coverage==2.0 pytest==9.0.2

# Full installation
python -m pip install --no-index --find-links /path/to/cocotb_offline/wheels_p12 \
  /path/to/cocotb_offline/wheels_p12/*.whl
```

### Adding new dependencies

When adding new Python packages for offline use:
1. Build/download wheels for Python 3.12 (cp312 ABI) on manylinux2014
2. Place wheels in `cocotb_offline/wheels_p12/`
3. **Append** wheel hashes to `wheels_p12.hash` (do not overwrite existing entries)

## Environment Configuration

### Target Environment (cocotb_vcs)

- **Shell**: csh/tcsh (scripts use csh syntax)
- **Python**: 3.12.7 (from Anaconda at `/tools/ctools/rh7.9/anaconda3/2024.10/bin`)
- **GCC**: 9.2.0 (from `/tools/hydora64/hdk-r7-9.2.0/22.10`)
- **EDA**: VCS 2023.03-SP2, Verdi 2023.03-SP2 (via environment modules)
- **License**: Pre-configured for VCS/Verdi

### Development Environment (cocotb_ex)

- **Shell**: bash
- **Python**: 3.12.x (any cp312 ABI)
- **Tools**: Verilator, GTKWave, lcov (genhtml, verilator_coverage)

## Important Constraints

1. **Shell Compatibility**: cocotb_vcs uses csh/tcsh for environment setup (cfg_env.csh). Use `source cfg_env.csh` before running simulations.

2. **Python/cocotb Version**: Use Python 3.12.7 with cocotb 2.0.1. The wheelhouse is built for cp312 ABI.

3. **Coverage Merging**: Coverage can only be merged for runs with identical compilation configurations (TOPLEVEL/RTL_FILELISTS/TOP_PARAMS/compile args). Changing these requires a separate coverage database.

4. **PATH Issues**: Always use `make doctor` before running simulations to verify:
   - Python interpreter and cocotb availability
   - VCS/Verdi/Verilator in PATH
   - Filelists and wrapper files exist
   - VPI libraries (libcocotbvpi_vcs.so or libcocotbvpi_verilator.so) are found

5. **Variable Origin**: Makefile uses `$(origin VAR)` to detect command-line vs environment vs default. Module names are passed via make variables, not environment variables.

## Regression Architecture

Two regression entry points:

1. **make regress** - Single TOP, multiple modules/seeds. Calls `run_regression.sh`.
2. **make suite** - Multi-TOP matrix. Calls `run_template_suite.sh`.

Key regression variables:
- `REGR_MODULES` - Space-separated list of Python test modules
- `REGR_SEEDS` - Space-separated list of random seeds
- `REGR_OUT` - Regression output directory
- `REGR_REBUILD=1` - Clean before each regression iteration

## Filelist Expansion

The Makefile uses `expand_filelists.py` to:
- Parse filelists with `-f` recursive includes
- Extract compile args (`+incdir+`, `+define+`, etc.)
- Validate source files exist

Filelists support:
- Relative paths (from filelist location)
- `-f other.f` for recursive includes
- `+incdir+dir` for include paths
- `+define+MACRO` for macros
- `//` comments and blank lines

## Debugging Issues

1. Run `make doctor` first - most issues are caught here
2. Check ISSUE.md in each subdirectory for known issues and workarounds
3. For VCS waveform issues, try `make WAVES=0` to verify simulation works without FSDB
4. For coverage errors (`[UCAPI-DNYL] Design not yet loaded`), use absolute paths for COV_DIR or run `make clean_out && make sim`
5. Check `wheels_p12.hash` when updating offline dependencies

## Docker for Offline Testing

A ManyLinux 2014 Docker container is used to reproduce the target offline environment:

```bash
docker run --hostname=0450485939d6 -v /home/user/work/verilog_sim_template:/data ...
```

The container mounts the repo at `/data` and provides GCC 9.2.0 for wheel building.
