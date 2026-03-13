# cocotb + Verilator/GTKWave 模板（cocotb_ex）

`cocotb_ex/` 是 `cocotb_vcs/` 的**外网/开源对照版本**：`rtl/`、`tb/`、`tests/`、`filelists/` 保持一致，仅将 `sim/` 的编译/运行/波形/覆盖率流程替换为开源工具链（Verilator + GTKWave + verilator_coverage）。

## 目录结构

```
cocotb_ex/
  rtl/            # DUT 代码（与 cocotb_vcs 同步）
  filelists/      # RTL filelist（可多层 -f 递归）
  tb/             # 可复用 cocotb testbench（Python + HDL wrapper，与 cocotb_vcs 同步）
    hdl/          # tb_top.sv / tb_fifo.sv
  tests/          # 具体 test case（与 cocotb_vcs 同步）
  sim/            # 仿真入口（Makefile / 脚本，Verilator 版本）
    sim_build/    # 编译/仿真中间产物（默认按 TOPLEVEL 分目录）
    out/          # 每次运行输出（默认按 CASE/SEED 分目录：results/VCD/coverage）
    regression_out/  # suite/regress 运行日志
```

## 使用方法

进入仿真目录：

```bash
cd cocotb_ex/sim
```

### Python（cp312）与离线安装

- 建议使用 Python `3.12.7`（或至少同为 `cp312` ABI 的 `3.12.x`），并安装 `cocotb==2.0.1`。
- 仿真时用 `PYTHON_BIN` 选择解释器（避免 `python/cocotb` 不一致）：

```bash
make doctor PYTHON_BIN=/path/to/python3.12
make sim    PYTHON_BIN=/path/to/python3.12
```

- wheelhouse 离线安装命令参考：`cocotb_offline/wheels_p12/README.md`
- `cocotb_ex` 不提供 `cfg_env.csh`（该脚本仅用于内网 VCS 环境）；请自行准备 Verilator/GTKWave/LCOV 环境。

0.（推荐）首次运行前做一次环境自检：

```bash
make doctor
make doctor DOCTOR_OUT=doctor.log
```

1. 运行默认用例：

```bash
make
```

2. 指定位宽/随机种子/用例数：

```bash
make W=16 SEED=1 N=500
```

### Verilator 参数覆盖（TOP_PARAMS）

本模板默认使用 Verilator 顶层参数覆盖语法 `-G<name>=<value>`：

- 默认：`TOP_PARAMS=-GW=<W>`
- FIFO 例子（同时覆盖 `W/DEPTH`）：

```bash
make TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f MODULE=tests.test_fifo TESTCASE=run_fifo_random \
     TOP_PARAMS="-GW=16 -GDEPTH=32" SEED=2 N=500
```

## 波形（VCD + GTKWave）

- 默认开启波形：`WAVES=1`（Verilator trace），输出：
  - `cocotb_ex/sim/out/<CASE>/seed<SEED>/waves.vcd`
- 关闭波形（加速回归）：`make WAVES=0`
- 波形范围（best-effort）：`WAVE_SCOPE=dut` 会传入 `+DUT_ONLY`（仅对 HDL 中 `$dumpvars` 范围有影响）

打开波形（需要图形界面/`DISPLAY` 可用）：

```bash
make gtkwave CASE=<CASE> SEED=<SEED>
```

或直接：

```bash
gtkwave cocotb_ex/sim/out/<CASE>/seed<SEED>/waves.vcd
```

## 调试/日志

- `DEBUG=1`：开启 Verilator debug（编译更慢）
- `SIM_LOG=sim.log`：重定向仿真 stdout/stderr 到文件
- `COMPILE_LOG=compile.log`：重定向 Verilator 编译输出（best-effort）

## 覆盖率（Verilator coverage）

- 默认开启覆盖率：`COV=1`
- 每次运行都会输出：
  - `cocotb_ex/sim/out/<CASE>/seed<SEED>/coverage.dat`
- 可覆盖输出路径：`COV_DAT_FILE=/path/to/coverage.dat`

生成 HTML 覆盖率报告（会自动合并该 `CASE` 下所有 seed 的 `coverage.dat`）：

```bash
make cov CASE=<CASE>
```

输出：

- `cocotb_ex/sim/out/<CASE>/cov/cov_html/index.html`

### 目录结构与合并策略

- 覆盖率按 `CASE` 归档；同一 `CASE` 下不同 seed 的 `coverage.dat` 会在 `make cov CASE=<CASE>` 时合并为一份 `lcov.info`。
- `CASE` 等价于**一次编译配置**（`TOPLEVEL/RTL_FILELISTS/TOP_PARAMS/宏定义/编译参数` 等）。参数一旦改变，覆盖率**不能合并**。

合并多个 case（同一 DUT/相同编译配置）的示例（将 `out` 替换为你的 `OUT_ROOT`）：

```bash
# 方式 A：直接合并 coverage.dat
verilator_coverage --write-info out/merged/cov/lcov.info \
  out/<CASE1>/seed*/coverage.dat out/<CASE2>/seed*/coverage.dat
genhtml -o out/merged/cov/cov_html out/merged/cov/lcov.info

# 方式 B：合并已有 lcov.info
lcov -a out/<CASE1>/cov/lcov.info -a out/<CASE2>/cov/lcov.info -o out/merged/cov/lcov.info
genhtml -o out/merged/cov/cov_html out/merged/cov/lcov.info
```

如需关闭覆盖率（更快）：

```bash
make COV=0
```

## 输出目录与 TESTCASE 说明

输出目录相关变量（均可在命令行覆盖）：

- `OUT_ROOT`：输出根目录（默认 `out`）
- `CASE`：用例标签（默认由 `TOPLEVEL/MODULE/TESTCASE` 拼出）
- `SEED`：随机种子（默认 `42`）
- `CASE_DIR`：默认 `out/<CASE>`
- `RUN_DIR`：默认 `out/<CASE>/seed<SEED>`
- `COV_DAT_FILE`：默认 `out/<CASE>/seed<SEED>/coverage.dat`

关于 `TESTCASE` 与波形/结果文件：

- cocotb 2.x 推荐使用 `COCOTB_TEST_MODULES/COCOTB_TESTCASE/COCOTB_PLUSARGS`；本模板仍兼容 `MODULE/TESTCASE/PLUSARGS`（会自动映射）。
- `CASE` 默认会包含 `TESTCASE`（如果设置了 `TESTCASE=...`），因此**逐个指定 `TESTCASE`** 时，每个 case 会落在不同目录，VCD/结果天然隔离。
- 若**不设置** `TESTCASE`，cocotb 通常会在**同一次仿真**里执行该 `MODULE` 内的多个 `@cocotb.test()`，因此同一个 `SEED` 通常只会生成一份 `waves.vcd`/`results.xml`（包含多个 case 的结果）。
  - 如需“每个 case 独立波形/结果”，请像 `make suite` 一样，每次只跑一个 `TESTCASE`。

## 清理

```bash
make clean
```

- `make clean`：清理编译/仿真中间产物（如 `sim_build/`），默认**保留** `out/`（便于回溯）。
- `make clean_out`：清理 `out/` 与 `sim/regression_out/`。
- `make distclean`：等价于依次执行 `make clean` + `make clean_out`。

## 多 DUT / 多 TOP

- 多 DUT：通过不同的 `RTL_FILELISTS` 指向不同 DUT/子系统 filelist 即可复用该模板。
- 多 TOP：默认 wrapper 为 `tb/hdl/<TOPLEVEL>.sv`，可用 `TB_SOURCES=...` 覆盖。

内置两套 demo：

- adder：`TOPLEVEL=tb_top`，`MODULE=tests.test_adder`
- fifo ：`TOPLEVEL=tb_fifo`，`MODULE=tests.test_fifo`（`RTL_FILELISTS=../filelists/fifo.f`）

## 回归（regress）与套件（suite）

`make regress` 会在当前 `TOPLEVEL/RTL_FILELISTS/...` 组合下，按模块与种子循环调用 `make sim`，日志默认输出到 `sim/regression_out/`。

示例：回归 fifo（1 个 module，多 seed）：

```bash
cd cocotb_ex/sim
make regress TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f \
  REGR_MODULES="tests.test_fifo" REGR_SEEDS="1 2 3"
```

常用回归变量（`sim/run_regression.sh` 读取）：

- `REGR_MODULES="tests.test_a tests.test_b"`：显式指定回归模块列表
- `REGR_SEEDS="1 2 3"`：回归种子列表（不设则使用 `SEED` 或默认 `42`）
- `REGR_OUT=path`：回归输出目录（默认 `sim/regression_out/`）
- `REGR_REBUILD=1`：每轮回归前先 `make clean`（避免复用旧产物）
- `REGR_SAVE_LOGS=0`：不保存 `sim_*.log/compile.log`（默认保存）
- `REGR_CASE=case_name`：强制统一 CASE（默认 `TOPLEVEL__<module>`）
- `REGR_COV_DAT_FILE=/path/to/coverage.dat`：强制覆盖率输出文件（默认按 CASE/SEED）
- `REGR_DEBUG=1`：输出 `regress_debug.log`（记录模块/CASE/COV_DAT_FILE 等）

关键变量关系与优先级（避免目录错配）：

- `COCOTB_TEST_MODULES`：当前单次仿真的 cocotb 模块（推荐使用）；`MODULE` 为旧变量，仅在 `COCOTB_TEST_MODULES` 未显式设置时才会映射
- `REGR_MODULES`：回归入口使用的模块列表；未设置时退化为 `MODULE` 或扫描 `tests/test_*.py`
- `CASE`：输出目录命名（默认 `TOPLEVEL__<module>__<testcase>`，无 testcase 时不包含）
  - 回归时可用 `REGR_CASE` 覆盖（对所有 run 生效）
- `COV_DAT_FILE`：覆盖率数据文件（默认 `out/<CASE>/seed<SEED>/coverage.dat`）
  - 回归时可用 `REGR_COV_DAT_FILE` 覆盖（对所有 run 生效）

`make suite`：模板内置套件（2 个 TOP × 2 个 case × 2 个 seed），可用 `REGR_SEEDS="1 2"`/`REGR_OUT=...` 覆盖种子列表与输出目录。

## Manual Pipeline Execution

You can execute specific roles of the AI pipeline manually using `cocotb_ex/ai_cli_pipeline/run_pipeline.py`. This is useful for debugging or running specific steps without triggering the entire workflow.

**Command Syntax:**
```bash
python3 cocotb_ex/ai_cli_pipeline/run_pipeline.py --role <ROLE_NAME>
```

**Note:** The pipeline script automatically loads configuration from `config.json`. Some parameters are injected dynamically or have defaults, but you may need to ensure the environment (e.g., Docker images) is ready.

### Examples

#### 1. Run Regression (regress_runner)
To run the regression runner manually. Note that `regress_runner` typically relies on metadata generated by previous steps (like `dv_agent`) or defaults in `config.json`.

**Basic Run (uses defaults/metadata):**
```bash
python3 cocotb_ex/ai_cli_pipeline/run_pipeline.py --role regress_runner
```

**Run with Overrides (via config modification):**
The CLI currently does not support passing arbitrary parameters (like `top_level`) directly via command line flags to override `config.json` values for a single run. To change parameters for a manual run, you should either:
1.  Edit `cocotb_ex/ai_cli_pipeline/config.json` (or `config.local.json`) temporarily.
2.  Or ensure the environment/metadata files (e.g., `artifacts/dv_metadata.json`) contain the desired values.

*Example scenario: The regression runner failed because `TOPLEVEL` was missing. After fixing `config.json` to include `"top_level": "ai_tb_top"` for the `regress_runner` role, you simply run:*
```bash
python3 cocotb_ex/ai_cli_pipeline/run_pipeline.py --role regress_runner
```

#### 2. Run Simulation (sim_runner)
```bash
python3 cocotb_ex/ai_cli_pipeline/run_pipeline.py --role sim_runner
```

#### 3. Run Code Formatter
```bash
python3 cocotb_ex/ai_cli_pipeline/run_pipeline.py --role code_formatter
```

## 常见问题

- **AI Pipeline / Docker 环境问题**：
  - **现象**：执行 `make implement` 或 `make pipeline` 时，Agent（如 `de_agent`）启动后立即退出，日志为空或报错找不到 `opencode`。
  - **原因**：通常是因为 `git pull` 更新了代码（增加了新的工具依赖），但本地的 Docker 镜像 `ai-cli:latest` 未同步更新。
  - **解决**：进入 Docker 配置目录并重新构建镜像：
    ```bash
    cd cocotb_ex/ai_cli_pipeline/docker
    docker compose build
    ```
- `ccache` 权限导致 Verilator 编译失败：本模板默认通过 `BUILD_ARGS += OBJCACHE=` 禁用 ccache；如需启用可在命令行覆盖 `BUILD_ARGS`。
- `gtkwave` 无法打开：通常是无图形界面/`DISPLAY` 不可用；可在有 GUI 的机器上打开 `waves.vcd`。

## 其他修改记录：
- 本地Terminal由bash修改为tcsh: vscode进入wsl时默认用tcsh打开Terminal(已删除)
`~/.vscode-server/data/Machine$ settings.json中添加如下内容：`
`    "terminal.integrated.profiles.linux": {`
`        "tcsh": { "path": "/usr/bin/tcsh" }`
`    },`
`    "terminal.integrated.defaultProfile.linux": "tcsh"`
