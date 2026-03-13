# cocotb_vcs：cocotb + VCS/Verdi 仿真模板

本模板用于在 Synopsys VCS 下运行 cocotb，用 Verdi/FSDB 查看波形，并支持覆盖率（urg）与回归。

## 环境初始化（csh/tcsh）

环境默认使用 c shell 系（csh/tcsh）。进入 `cocotb_vcs/` 后先加载环境脚本：

```csh
cd cocotb_vcs
source cfg_env.csh
```

`cfg_env.csh` 会完成：

- 前置 Python：`setenv PATH /tools/ctools/rh7.9/anaconda3/2024.10/bin:${PATH}`（Python 3.12.7，现状：已安装 cocotb 相关依赖）
- 设置 GCC：`setenv GCC_HOME /tools/hydora64/hdk-r7-9.2.0/22.10` 并更新 `PATH/LD_LIBRARY_PATH`
- 加载 EDA：`module load vcs/2023.03-SP2`、`module load verdi/2023.03-SP2`

如何确认当前交互 shell：

```csh
echo $SHELL
ps -p $$ -o comm=
```

## 最简命令（跑通默认用例）

注意：以下命令默认在 `cocotb_vcs/sim` 目录执行（除非命令里包含路径）。

```csh
cd cocotb_vcs
source cfg_env.csh
cd sim
make
```

## 常用命令速查（多 TB / 多 TOP / 多 case / 多 seed）

注意：以下命令默认在 `cocotb_vcs/sim` 目录执行（除非命令里包含路径）。

```csh
# 假设已完成环境初始化：cd cocotb_vcs && source cfg_env.csh

# 0) 建议每台机器第一次先做自检（可留档）
cd cocotb_vcs/sim
make doctor
make doctor DOCTOR_OUT=doctor.log

# 1) adder：单个 case + 多 seed
make TOPLEVEL=tb_top MODULE=tests.test_adder TESTCASE=run_adder_smoke SEED=1
make TOPLEVEL=tb_top MODULE=tests.test_adder TESTCASE=run_adder_random SEED=2 N=500
foreach s (1 2 3)
  make TOPLEVEL=tb_top MODULE=tests.test_adder TESTCASE=run_adder_smoke SEED=$s
end

# 2) fifo：切 TOP + 切 TB（多 TOP / 多 TB）
make TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f MODULE=tests.test_fifo TESTCASE=run_fifo_smoke SEED=1
make TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f MODULE=tests.test_fifo TESTCASE=run_fifo_random SEED=2 N=500 \
  TOP_PARAMS="-pvalue+tb_fifo.DEPTH=32 -pvalue+tb_fifo.W=16"

# 3) 一键跑模板套件：2 TOP × 2 case × 多 seed
make suite REGR_SEEDS="1 2"
```

## 环境要求

- Python：用 `which python` + `python --version` 确认当前解释器路径与版本是否正确（期望指向 `setenv PATH /tools/ctools/rh7.9/anaconda3/2024.10/bin:${PATH}` 的 Python 3.12.7，现状：已安装 cocotb 相关依赖）
  - 若机器上有多个 Python：优先通过 `PATH` 选择；或用 `make PYTHON_BIN=/path/to/python3.12 ...` 指定解释器
- EDA：`vcs`、`verdi`（FSDB 波形需要）与 `urg`（覆盖率报告需要），并已配置 license
- GCC：建议使用 `/tools/hydora64/hdk-r7-9.2.0/22.10` 提供的 gcc 工具链（避免 VCS/PLI 编译链版本不一致）

## 从 0 开始：跑通一次仿真

0) 先初始化环境（建议）：

```csh
cd cocotb_vcs
source cfg_env.csh
```

1) 确认工具可用：

```csh
which vcs verdi urg python3
python3 -V
python3 -m cocotb_tools.config --version
```

2) 进入仿真目录并自检：

提示：从这一步开始，后续命令默认在 `cocotb_vcs/sim` 下执行。

```csh
cd cocotb_vcs/sim
make doctor
```

3) 跑默认用例（`tb_top` + `tests.test_adder`）：

```csh
make            # 等价 make sim
make WAVES=0    # 关闭波形加速（可选）
```

4) 打开波形（默认 FSDB 输出到 `sim/out/.../waves.fsdb`）：

```csh
make verdi
```

5) 清理：

```csh
make clean       # 清理 sim_build/，默认保留 out/
make clean_out   # 清理 out/ 与 sim/regression_out/
make distclean   # clean + clean_out
```

## 如何替换/新增：TOP / TB / case / DUT

模板的组合关系：

- **TOP**：HDL wrapper（`tb/hdl/<TOPLEVEL>.sv`），负责例化 DUT、提供时钟/复位信号，并可导出波形
- **TB**：Python 可复用 testbench（建议放在 `tb/*.py`），封装 driver/monitor/scoreboard
- **case**：具体测试用例（`tests/test_*.py` 里的 `@cocotb.test()`）
- **DUT**：RTL 代码 + filelist（`filelists/*.f`）

### 1) 新增/替换 DUT（RTL + filelist）

1. 把 RTL 放到 `rtl/`（或工程任意目录）
2. 新建 `filelists/<dut>.f`，每行一个源文件路径；支持 `-f other.f` 递归、`+incdir+...`、`+define+...` 等选项
3. 运行时切换：

```csh
make RTL_FILELISTS=../filelists/<dut>.f ...
```

如同一个 `TOPLEVEL` 下切换了不同的 `RTL_FILELISTS`，建议显式指定 `SIM_BUILD` 避免复用旧产物：

```csh
make TOPLEVEL=tb_top RTL_FILELISTS=../filelists/<dut>.f SIM_BUILD=sim_build/<dut> ...
```

### 2) 新增/替换 TOP（HDL wrapper）

1. 在 `tb/hdl/` 下新增 `tb_<name>.sv`，并确保模块名与文件名一致（例如 `module tb_<name> ...`）
2. wrapper 内例化 DUT（建议实例名为 `dut`，便于 `WAVE_SCOPE=dut` 与常用脚本）
3. 运行时选择：

```csh
make TOPLEVEL=tb_<name> ...
```

如 wrapper 需要顶层参数，可用 `TOP_PARAMS` 覆盖默认的 `-pvalue+<TOPLEVEL>.W=<W>`：

```csh
make TOPLEVEL=tb_<name> TOP_PARAMS="-pvalue+tb_<name>.W=16 -pvalue+tb_<name>.DEPTH=32" ...
```

### 3) 新增 TB（Python 可复用 testbench）

建议把可复用的 driver/monitor/scoreboard 放到 `tb/` 下，例如 `tb/<dut>_tb.py`，然后在 case 中复用：

```python
from tb.<dut>_tb import MyTB
```

本模板已在 `tb/adder_tb.py`、`tb/fifo_tb.py` 给出示例结构。

### 4) 新增 case（tests/test_*.py）

1. 在 `tests/` 新建 `test_<dut>.py`
2. 用 `@cocotb.test()` 添加用例函数
3. 运行方式：

```csh
make MODULE=tests.test_<dut>                  # 跑该 module 里的全部 @cocotb.test()
make MODULE=tests.test_<dut> TESTCASE=<case>  # 只跑某一个 case
```

示例（已有 fifo 的第二套用例）：

```csh
make TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f \
  MODULE=tests.test_fifo_2 TESTCASE=run_fifo_directed
```

## 常用参数说明

- `TOPLEVEL`：顶层 wrapper 模块名（默认 `tb_top`）
- `RTL_FILELISTS`：一个或多个 filelist（空格分隔）
- `MODULE`：cocotb 测试模块（例如 `tests.test_adder`）
- `TESTCASE`：用例函数名（例如 `run_adder_smoke`）；不设置则同一次仿真跑完该 module 的多个 case
- `SEED`：随机种子（传给 Python，默认 `42`）
- `N`：用例规模（示例用在 random case 中）
- `PYTHON_BIN`：指定 Python 解释器（默认 `python3`）

输出目录默认按 `CASE/SEED` 分层，避免互相覆盖：

- `OUT_ROOT`：输出根目录（默认 `out`）
- `CASE_DIR`：默认 `out/<CASE>`
- `RUN_DIR`：默认 `out/<CASE>/seed<SEED>`（包含 `results.xml`、`waves.fsdb` 等）

## 波形/调试/日志

- `WAVES=0`：关闭 FSDB（最快）
- `WAVE_SCOPE=dut`：只 dump `tb_*.dut`（更小更快）
- `DEBUG=0`：关闭 `-kdb -debug_access+all`，减少编译开销
- `QUIET=1`：降低 VCS 编译信息输出
- `COMPILE_LOG=compile.log` / `SIM_LOG=sim.log`：将编译/仿真日志写入文件

## 覆盖率（urg）

默认开启 `COV=1`，仿真后生成覆盖率数据目录 `out/<CASE>/cov/cm.vdb`。生成 HTML 报告：

```csh
cd cocotb_vcs/sim
make sim
make cov
```

### 目录结构与合并策略（初版）

- 覆盖率数据库：`out/<CASE>/cov/cm.vdb`（由 `-cm_dir` 写入）
- 覆盖率报告：`out/<CASE>/cov/cov_html/index.html`（由 `urg` 生成）
- 同一 `CASE` 下不同 seed 建议复用同一个 `COV_DIR`，VCS 会把数据累积进同一 `cm.vdb`。
- `CASE` 等价于**一次编译配置**（`TOPLEVEL/RTL_FILELISTS/TOP_PARAMS/宏定义/COV_TYPES/编译参数` 等）。参数一旦改变，覆盖率**不能合并**。

合并多个 case（同一 DUT/相同编译配置）的示例（将 `out` 替换为你的 `OUT_ROOT`）：

```csh
urg -dir out/<CASE1>/cov/cm.vdb -dir out/<CASE2>/cov/cm.vdb -report out/merged_cov
```

常见报错：`[UCAPI-DNYL] Design not yet loaded`

- 通常是 `-cm_dir` 写入位置不一致（design/test 分散到不同目录或旧产物混杂）
- 处理建议：
  - `make clean_out && make sim && make cov`
  - 或显式固定目录：`make sim COV_DIR=$cwd/cm.vdb && make cov COV_DIR=$cwd/cm.vdb`

## 回归（regression）

模板提供两种回归入口：

- `make regress`：单 TOP 回归驱动（调用 `sim/run_regression.sh`），对当前这一套 `TOPLEVEL/RTL_FILELISTS/TB_SOURCES/...` 做多次运行
- `make suite`：模板内置套件（调用 `sim/run_template_suite.sh`），用于演示“多 TOP × 多 case × 多 seed”

### 1) `make regress`（单 TOP 回归，推荐用于工程脚本化）

切换 `TOPLEVEL/RTL_FILELISTS/MODULE` **不需要修改 Makefile**，直接在命令行覆盖即可。

示例：回归 fifo（1 个 module，多 seed）：

```csh
cd cocotb_vcs/sim
make regress TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f \
  REGR_MODULES="tests.test_fifo" REGR_SEEDS="1 2 3"
```

示例：回归 fifo（2 个 module，多 seed）：

```csh
cd cocotb_vcs/sim
make regress TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f \
  REGR_MODULES="tests.test_fifo tests.test_fifo_2" REGR_SEEDS="1 2 3"
```

#### `REGR_MODULES/REGR_SEEDS` 是什么？怎么传？

`REGR_MODULES/REGR_SEEDS/REGR_OUT/...` 是 `sim/run_regression.sh` 读取的变量，用来控制“跑哪些 module、跑哪些 seed、输出到哪里”。

两种写法等价（选一种即可）：

```csh
# 写法 A：作为 make 变量（推荐，可读性更好）
make regress REGR_MODULES="tests.test_fifo" REGR_SEEDS="1 2 3" ...

# 写法 B：作为 shell 环境变量（仅对这条命令生效）
# - csh/tcsh 不支持 `VAR=... cmd`，请用 `env VAR=... cmd` 或直接用写法 A
env REGR_MODULES="tests.test_fifo" REGR_SEEDS="1 2 3" make regress ...
```

> `VAR=... cmd` 是 shell 语法：给 `cmd` 进程临时添加环境变量；不是 “make 的目标/参数”。

#### 常用回归变量（`sim/run_regression.sh`）

- `REGR_MODULES="tests.test_a tests.test_b"`：显式指定回归模块列表
- `REGR_SEEDS="1 2 3"`：回归种子列表（不设则使用 `SEED` 或默认 `42`）
- `REGR_OUT=path`：回归输出目录（默认 `sim/regression_out/`）
- `REGR_REBUILD=1`：每轮回归前先 `make clean`（避免复用旧产物）
- `REGR_SAVE_LOGS=0`：不保存 `sim_*.log/compile.log`（默认保存，便于环境问题定位）

输出文件在 `REGR_OUT/` 下（例如：`results_<idx>.xml`、`sim_<idx>.log`、`doctor.log`）。

#### 关键变量关系与优先级（避免目录错配）

- `COCOTB_TEST_MODULES`：**当前单次仿真**的 cocotb 测试模块（推荐用它）；`MODULE` 为旧变量，仅在 `COCOTB_TEST_MODULES` 未显式设置时才会被映射
- `REGR_MODULES`：回归入口使用的模块列表（空格分隔）；仅影响 `make regress`/`run_regression.sh`
  - 若未设置 `REGR_MODULES`：脚本会先看 `MODULE`，再退化为扫描 `tests/test_*.py`
- `COCOTB_TESTCASE`：指定单个 case；`TESTCASE` 为旧变量，未显式设置 `COCOTB_TESTCASE` 时才会映射
- `CASE`：输出目录命名（默认 `TOPLEVEL__<module>__<testcase>`，无 testcase 时不包含）
  - `CASE` 决定 `CASE_DIR/RUN_DIR`（results/waves 等）
  - 回归时可用 `REGR_CASE` 覆盖（对所有 run 生效）
- `COV_DIR`：**仅**影响覆盖率 `-cm_dir`（默认 `out/<CASE>/cov/cm.vdb`），不影响 `RUN_DIR`
  - 回归脚本会按当前 `CASE` 自动计算 `COV_DIR`
  - 如需覆盖：`make regress ... COV_DIR=out/<CASE>/cov/cm.vdb`（会透传为 `REGR_COV_DIR`）

补充：`env | egrep '^(CASE|MODULE|COCOTB_TEST_MODULES)='` 只能显示**环境变量**，Makefile 内部默认值不会出现在 `env` 里；因此 shell 里 `echo $COV_DIR` 可能显示 “Undefined”，但 make 仍会使用默认值。

### 2) 多 TOP 回归：两种做法

#### 做法 A：脚本/循环多次调用 `make regress`（每次一套 TOP/RTL）

把多条 `make regress` 写进一个脚本/for 循环即可，不需要手工一条条敲。

示例（同一个 shell 中跑两套 TOP）：

```csh
cd cocotb_vcs/sim
make regress TOPLEVEL=tb_top  RTL_FILELISTS=../filelists/rtl.f  REGR_MODULES="tests.test_adder" REGR_SEEDS="1 2" REGR_OUT=regression_out/adder
make regress TOPLEVEL=tb_fifo RTL_FILELISTS=../filelists/fifo.f REGR_MODULES="tests.test_fifo"  REGR_SEEDS="1 2" REGR_OUT=regression_out/fifo
```

> 多次调用 `make regress` 时，建议每次设置不同的 `REGR_OUT`，否则 `results_*.xml/doctor.log` 等会被后一次覆盖。

等价的 for 循环写法（便于脚本化）：

```csh
cd cocotb_vcs/sim
foreach top (tb_top tb_fifo)
  if ( "$top" == "tb_top" ) then
    set fl = ../filelists/rtl.f
    set mod = tests.test_adder
  else if ( "$top" == "tb_fifo" ) then
    set fl = ../filelists/fifo.f
    set mod = tests.test_fifo
  endif
  make regress TOPLEVEL=$top RTL_FILELISTS=$fl REGR_MODULES=$mod REGR_SEEDS="1 2" REGR_OUT=regression_out/$top
end
```

#### 做法 B：使用/修改 `make suite`（模板内置矩阵）

`make suite` 会调用 `sim/run_template_suite.sh`，默认矩阵为：

- 2 TOP：`tb_top` / `tb_fifo`
- 2 case：`run_adder_smoke/run_adder_random`、`run_fifo_smoke/run_fifo_random`
- 多 seed：由 `REGR_SEEDS` 控制（默认 `1 2`）

用法：

```csh
cd cocotb_vcs/sim
make suite
make suite REGR_SEEDS="1 2 3" REGR_OUT=regression_out/my_suite
```

如何扩展 suite（新增设计/新增 TOP/新增 case）：

1. 准备好三件套：
   - `filelists/<dut>.f`
   - `tb/hdl/tb_<dut>.sv`（模块名 `tb_<dut>`）
   - `tests/test_<dut>.py`（包含你的 `@cocotb.test()` case 名）
2. 编辑 `cocotb_vcs/sim/run_template_suite.sh` 底部矩阵，新增一行 `run_one`：
   - `run_one "<TOPLEVEL>" "${ROOT_DIR}/filelists/<dut>.f" "tests.test_<dut>" "<case>" "${seed}"`
3.（可选）不想改模板默认 suite：复制脚本为 `cocotb_vcs/sim/run_my_suite.sh`，按需修改矩阵，然后二选一：
   - 直接执行脚本：

     ```csh
     cd cocotb_vcs/sim
     env REGR_SEEDS="1 2 3" REGR_OUT=regression_out/my_suite PYTHON_BIN=python3 ./run_my_suite.sh
     ```

   - 在 `cocotb_vcs/sim/Makefile` 增加一个新目标调用它（注意 Makefile 命令行需要 TAB）：

     ```makefile
     .PHONY: my_suite
     my_suite:
     	PYTHON_BIN="$(PYTHON_BIN)" \
     	REGR_SEEDS="$(REGR_SEEDS)" \
     	REGR_OUT="$(REGR_OUT)" \
     	./run_my_suite.sh
     ```

     然后执行：`cd cocotb_vcs/sim && make my_suite REGR_SEEDS="1 2 3" REGR_OUT=regression_out/my_suite`

## doctor（环境自检）

`make doctor` 会检查：

- `PYTHON_BIN` 与 cocotb 是否可用（含 `libcocotbvpi_vcs.so` 路径）
- `vcs/verdi/urg` 是否在 `PATH`
- wrapper/filelist 是否存在并可展开（快速发现路径/递归 filelist 问题）
- FSDB/Verdi PLI 的 `verdi.tab/pli.a` 探测结果（当 `WAVES=1` 时）

留档：

```csh
make doctor DOCTOR_OUT=doctor.log
```

## 常见问题（排查顺序）

1) 先跑：`cd cocotb_vcs/sim && make doctor`（大部分路径/工具/波形/覆盖率问题在这里就能定位）

2) `vcs: command not found`：检查 `PATH` / module / setup 脚本

3) `WAVES=1` 相关报错：先用 `make WAVES=0` 验证仿真主体；再补齐 `VERDI_HOME/VERDI_PLI_TAB/VERDI_PLI_LIB`

4) `ModuleNotFoundError: No module named 'tests'`：必须从 `cocotb_vcs/sim` 运行（或用 `sim/run_make.sh`）

5) `Unable to get the locale encoding` / `No module named 'encodings'`：检查python路径和版本（which python和python --version是否指向/tools/ctools/rh7.9/anaconda3/2024.10/bin，Python版本 3.12.7。现状：已安装 cocotb 相关依赖）
