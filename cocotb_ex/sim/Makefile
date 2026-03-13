# ========= 基本设置 =========
ROOT_DIR := $(abspath $(CURDIR)/..)

TOPLEVEL_LANG      = verilog
SIM                = verilator
TOPLEVEL           ?= tb_top

# cocotb 2.x 推荐变量（避免上游 Makefile 的 deprecation warning）
COCOTB_TEST_MODULES ?= tests.test_adder
COCOTB_TESTCASE ?=
COCOTB_PLUSARGS ?=

# 兼容旧变量（MODULE/TESTCASE/PLUSARGS）：若使用旧变量，则映射到 COCOTB_* 并清空旧变量
ifneq ($(strip $(MODULE)),)
  ifeq ($(filter command\ line environment,$(origin COCOTB_TEST_MODULES)),)
    COCOTB_TEST_MODULES := $(MODULE)
  endif
  override MODULE :=
endif
ifneq ($(strip $(TESTCASE)),)
  ifeq ($(filter command\ line environment,$(origin COCOTB_TESTCASE)),)
    COCOTB_TESTCASE := $(TESTCASE)
  endif
  override TESTCASE :=
endif
ifneq ($(strip $(PLUSARGS)),)
  ifeq ($(filter command\ line environment,$(origin COCOTB_PLUSARGS)),)
    COCOTB_PLUSARGS := $(PLUSARGS)
  endif
  override PLUSARGS :=
endif

# 默认目标：打印帮助（防止误触仿真）
.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Verilog Simulation Makefile"
	@echo "Usage:"
	@echo "  make sim       - Run simulation (TOPLEVEL=$(TOPLEVEL), MODULE=$(COCOTB_TEST_MODULES))"
	@echo "  make regress   - Run regression (defined in run_regression.sh)"
	@echo "  make cov       - Generate coverage report"
	@echo "  make clean     - Clean build artifacts (via root Makefile recommendation)"
	@echo ""
	@echo "Configuration:"
	@echo "  TOPLEVEL       = $(TOPLEVEL)"
	@echo "  MODULE         = $(COCOTB_TEST_MODULES)"
	@echo "  WAVES          = $(WAVES)"

# ========= 构建/输出目录（多 TOP / 多 CASE 友好）=========
# - SIM_BUILD：编译/运行目录（cocotb Makefile 使用），默认按 TOPLEVEL 分目录，避免多 top 冲突
# - OUT_ROOT/CASE_DIR/RUN_DIR：输出目录（results/waves/coverage），默认按 CASE/SEED 分层，避免覆盖

OUT_ROOT ?= out

empty :=
space := $(empty) $(empty)
sanitize = $(subst $(space),_,$(subst /,_,$(subst :,_,$(subst .,_,$(strip $(1))))))

MODULE_TAG := $(call sanitize,$(COCOTB_TEST_MODULES))
TESTCASE_TAG := $(call sanitize,$(COCOTB_TESTCASE))

# CASE：不包含随机种子，便于同一 case 多次跑不同 SEED
CASE ?= $(TOPLEVEL)__$(MODULE_TAG)$(if $(strip $(COCOTB_TESTCASE)),__$(TESTCASE_TAG),)
# CASE_DIR：按 case 归档（便于多 TOP / 多 case 管理输出）
CASE_DIR ?= $(OUT_ROOT)/$(CASE)
# RUN_DIR：按 seed 再分层，避免覆盖（同 case 不同 SEED 输出不互相覆盖）
RUN_DIR ?= $(CASE_DIR)/seed$(SEED)

# 覆盖 Makefile.inc 导出的 SIM_BUILD，避免在 suite/regress 脚本里被环境变量“粘住”到错误 TOPLEVEL
SIM_BUILD = sim_build/$(TOPLEVEL)
COCOTB_RESULTS_FILE = $(RUN_DIR)/results.xml

# ========= Python 解释器 =========
# 兼容 cocotb upstream 变量命名：优先使用 PYTHON_BIN（可在命令行覆盖）
PYTHON3 ?= python3
PYTHON_BIN ?= $(PYTHON3)
# 始终用与 PYTHON_BIN 绑定的 cocotb-config，避免 PATH 上的 cocotb-config 与 PYTHON_BIN 不一致
# - cocotb>=2.0:   python -m cocotb_tools.config
# - cocotb< 2.0:   python -m cocotb.config
COCOTB_CONFIG ?= $(PYTHON_BIN) -m cocotb_tools.config
COCOTB_CONFIG_FALLBACK ?= $(PYTHON_BIN) -m cocotb.config

# ========= Verilator 构建 =========
# 部分环境下 ccache 会因临时目录权限导致编译失败；默认显式使用 g++（可通过 BUILD_ARGS 覆盖）
BUILD_ARGS += CXX=g++
BUILD_ARGS += OBJCACHE=

# ========= 集群/LSF（bsub）=========
# 默认命令示例：bsub -Ip -q regr_high <cmd>
BSUB ?= bsub
BSUB_QUEUE ?= regr_high
BSUB_OPTS ?= -Ip -q $(BSUB_QUEUE)
# BSUB_WRAP=0: 直接提交命令（更接近: bsub ... verdi ... / bsub ... make ...）
# BSUB_WRAP=1: 用 shell 包一层（便于 cd/复杂参数；遇到参数转义问题时可开启）
BSUB_WRAP ?= 0
BSUB_SHELL ?= bash
BSUB_SHELL_OPTS ?= -lc

# ========= RTL 文件列表 =========
# 通过一个或多个 filelist 读入 RTL 源文件（每行一个路径，可用 -f 递归包含其他 filelist）
# 用法：make RTL_FILELISTS="path1.f path2.f"
RTL_FILELISTS ?= $(ROOT_DIR)/filelists/rtl.f

RTL_SOURCES   = $(shell $(PYTHON_BIN) $(CURDIR)/expand_filelists.py --sources $(RTL_FILELISTS))
FILELIST_COMPILE_ARGS = $(shell $(PYTHON_BIN) $(CURDIR)/expand_filelists.py --args $(RTL_FILELISTS))
COMPILE_ARGS  += $(FILELIST_COMPILE_ARGS)

# HDL wrapper（顶层）单独加入
TB_SOURCES ?= $(ROOT_DIR)/tb/hdl/$(TOPLEVEL).sv

VERILOG_SOURCES    = $(RTL_SOURCES) $(TB_SOURCES)

# filelist 变化时强制重新编译
CUSTOM_COMPILE_DEPS += $(RTL_FILELISTS) $(CURDIR)/expand_filelists.py

# 让 cocotb 找到 tb/ 和 tests/ 包
export PYTHONPATH := $(ROOT_DIR):$(PYTHONPATH)

# ========= 顶层参数 =========
# 顶层参数: MAX_CREDIT, FIFO_DEPTH (在 rtl/ai_dut.sv 和 tb/hdl/ai_tb_top.sv 中定义)
# 示例：make MAX_CREDIT=16 FIFO_DEPTH=32
# Verilator 使用 -G参数名=值 的语法
TOP_PARAMS ?= $(if $(MAX_CREDIT),-GMAX_CREDIT=$(MAX_CREDIT)) $(if $(FIFO_DEPTH),-GFIFO_DEPTH=$(FIFO_DEPTH))
COMPILE_ARGS      += $(TOP_PARAMS)

# ========= 波形（Verilator trace -> VCD）=========
# 可用 WAVES=0 关闭波形提升速度；默认输出到 RUN_DIR 下，避免多 seed 覆盖
WAVES ?= 1
WAVE_FILE ?= $(RUN_DIR)/waves.vcd
# 波形范围：默认全量；WAVE_SCOPE=dut 仅 dump dut（依赖 DUT_ONLY plusarg）
WAVE_SCOPE ?= full
ifeq ($(WAVE_SCOPE),dut)
  COCOTB_PLUSARGS += +DUT_ONLY
endif

ifeq ($(WAVES),1)
  COMPILE_ARGS += --trace --trace-structs
  SIM_ARGS += --trace --trace-file $(abspath $(WAVE_FILE))
endif

# ========= 调试（Verilator）=========
# DEBUG=1：启用 Verilator debug（更慢；用于 gdb/内部调试）
DEBUG ?= 0
VERILATOR_SIM_DEBUG ?= 0
ifeq ($(DEBUG),1)
  VERILATOR_SIM_DEBUG := 1
endif

# ========= 日志/输出控制 =========
# SIM_LOG：重定向仿真 stdout/stderr 到文件（编译输出仍在终端）
COMPILE_LOG ?=
SIM_LOG ?=
ifneq ($(SIM_LOG),)
  SIM_CMD_SUFFIX := > $(abspath $(SIM_LOG)) 2>&1
endif

# ========= 覆盖率（Verilator coverage）=========
# COV=1：编译启用 --coverage；运行时输出 coverage.dat（每个 seed 一份），用 `make cov` 合并并生成 HTML
COV ?= 1
COV_DAT_FILE ?= $(RUN_DIR)/coverage.dat
COV_INFO_FILE ?= $(CASE_DIR)/cov/lcov.info
COV_REPORT_DIR ?= $(CASE_DIR)/cov/cov_html
COV_INFO_FILE_ABS := $(abspath $(COV_INFO_FILE))
COV_REPORT_DIR_ABS := $(abspath $(COV_REPORT_DIR))
ifeq ($(COV),1)
  COMPILE_ARGS += --coverage
  COCOTB_PLUSARGS += +verilator+coverage+file+$(abspath $(COV_DAT_FILE))
endif

.PHONY: cov
cov:
	@if [ "$(COV)" != "1" ]; then \
	  echo "COV=0, skip coverage report."; \
	elif ! command -v verilator_coverage >/dev/null 2>&1; then \
	  echo "ERROR: verilator_coverage not found (check Verilator installation/PATH)."; exit 1; \
	elif ! command -v genhtml >/dev/null 2>&1; then \
	  echo "ERROR: genhtml not found (install lcov)."; exit 1; \
	else \
	  mkdir -p "$(dir $(COV_INFO_FILE_ABS))" "$(COV_REPORT_DIR_ABS)"; \
	  files="$(CASE_DIR)"/seed*/coverage.dat; \
	  set -- $$files; \
	  if [ "$$1" = "$(CASE_DIR)/seed*/coverage.dat" ]; then \
	    echo "ERROR: no coverage.dat found under $(CASE_DIR)/seed*/ (run sim with COV=1 first)."; exit 1; \
	  fi; \
	  verilator_coverage --write-info "$(COV_INFO_FILE_ABS)" $$files; \
	  genhtml -o "$(COV_REPORT_DIR_ABS)" "$(COV_INFO_FILE_ABS)" >/dev/null; \
	  echo "Coverage report -> $(COV_REPORT_DIR_ABS)/index.html"; \
	fi

# ========= 运行前自检（提升离线环境一次成功率）=========
.PHONY: precheck
precheck:
	@mkdir -p "$(RUN_DIR)" "$(SIM_BUILD)"
	@mkdir -p "$(dir $(abspath $(WAVE_FILE)))"
	@mkdir -p "$(dir $(abspath $(COCOTB_RESULTS_FILE)))"
	@mkdir -p "$(dir $(abspath $(COV_DAT_FILE)))"
	@mkdir -p "$(dir $(COV_INFO_FILE_ABS))"
	@mkdir -p "$(dir $(COV_REPORT_DIR_ABS))"
	@if [ -n "$(COMPILE_LOG)" ]; then mkdir -p "$(dir $(abspath $(COMPILE_LOG)))"; fi
	@if [ -n "$(SIM_LOG)" ]; then mkdir -p "$(dir $(abspath $(SIM_LOG)))"; fi
	@if command -v "$(PYTHON_BIN)" >/dev/null 2>&1; then \
	  :; \
	elif [ -x "$(PYTHON_BIN)" ]; then \
	  :; \
		else \
		  echo "ERROR: PYTHON_BIN not found or not executable: $(PYTHON_BIN)"; \
		  exit 1; \
		fi
		@$(PYTHON_BIN) -c "import encodings, locale; print('python ok:', locale.getpreferredencoding(False))" >/dev/null
		@$(COCOTB_CONFIG) --version >/dev/null 2>&1 || $(COCOTB_CONFIG_FALLBACK) --version >/dev/null 2>&1 || { echo "ERROR: cocotb not found for PYTHON_BIN=$(PYTHON_BIN) (try installing cocotb or setting PYTHON_BIN)."; exit 1; }
		@lib_dir=$$($(COCOTB_CONFIG) --lib-dir 2>/dev/null || $(COCOTB_CONFIG_FALLBACK) --lib-dir 2>/dev/null || true); \
		  lib="$$lib_dir/libcocotbvpi_verilator.so"; \
		  test -n "$$lib_dir" && test -f "$$lib" || { \
		    echo "ERROR: cocotb VPI library for Verilator not found: $$lib"; \
		    echo "Hint: check cocotb installation; expected libcocotbvpi_verilator.so under: $(COCOTB_CONFIG) --lib-dir"; \
		    exit 1; \
		  }
	@command -v verilator >/dev/null 2>&1 || { echo "ERROR: verilator not found in PATH."; exit 1; }
	@for fl in $(RTL_FILELISTS); do \
	  test -f "$$fl" || { echo "ERROR: RTL filelist not found: $$fl"; exit 1; }; \
	done
	@for f in $(TB_SOURCES); do \
	  test -f "$$f" || { echo "ERROR: TB_SOURCES not found: $$f (set TOPLEVEL or TB_SOURCES)"; exit 1; }; \
	done
	@$(PYTHON_BIN) $(CURDIR)/expand_filelists.py --check --sources $(RTL_FILELISTS) >/dev/null
	@if [ "$(COV)" = "1" ]; then \
	  command -v verilator_coverage >/dev/null 2>&1 || { echo "ERROR: verilator_coverage not found (required for make cov)."; exit 1; }; \
	  command -v genhtml >/dev/null 2>&1 || { echo "ERROR: genhtml not found (install lcov)."; exit 1; }; \
	fi

# ========= 随机种子/用例数（传给 tests）=========
export SEED ?= 42
export N    ?= 200

# 允许在未配置 Verilator/cocotb 的机器上仍能执行 `make doctor/clean/...` 做排查
SKIP_COCOTB_GOALS := doctor clean clean_out distclean gtkwave cov sim_bsub regress_bsub doctor_bsub cov_bsub
ifneq ($(MAKECMDGOALS),)
  NEED_COCOTB_GOALS := $(filter-out $(SKIP_COCOTB_GOALS),$(MAKECMDGOALS))
else
  NEED_COCOTB_GOALS := all
endif

ifneq ($(NEED_COCOTB_GOALS),)
include $(shell $(COCOTB_CONFIG) --makefiles 2>/dev/null || $(COCOTB_CONFIG_FALLBACK) --makefiles 2>/dev/null)/Makefile.sim

# Best-effort compile log redirection for Verilator (only affects compile phase).
ifneq ($(strip $(COMPILE_LOG)),)
  ifneq ($(strip $(CMD)),)
    CMD := $(CMD) > $(abspath $(COMPILE_LOG)) 2>&1
  endif
endif

# 确保仿真/编译前先做一次 precheck（避免内网环境难定位错误）
$(SIM_BUILD)/Vtop.mk: precheck
$(COCOTB_RESULTS_FILE): precheck
endif

.PHONY: gtkwave
gtkwave:
	@command -v gtkwave >/dev/null 2>&1 || { echo "ERROR: gtkwave not found in PATH."; exit 1; }
	@test -f "$(WAVE_FILE)" || { echo "ERROR: $(WAVE_FILE) not found. Run 'make' with WAVES=1 first."; exit 1; }
	@echo "Open $(WAVE_FILE) with gtkwave..."
	gtkwave "$(WAVE_FILE)" &

.PHONY: doctor
doctor:
	PYTHON_BIN="$(PYTHON_BIN)" \
	TOPLEVEL="$(TOPLEVEL)" \
	COCOTB_TEST_MODULES="$(COCOTB_TEST_MODULES)" \
	COCOTB_TESTCASE="$(COCOTB_TESTCASE)" \
	RTL_FILELISTS="$(RTL_FILELISTS)" \
	TB_SOURCES="$(TB_SOURCES)" \
	WAVES="$(WAVES)" \
	WAVE_SCOPE="$(WAVE_SCOPE)" \
	WAVE_FILE="$(WAVE_FILE)" \
	DEBUG="$(DEBUG)" \
	COV="$(COV)" \
	COV_DAT_FILE="$(COV_DAT_FILE)" \
	./doctor.sh

.PHONY: sim_bsub
sim_bsub:
	$(BSUB) $(BSUB_OPTS) $(if $(filter 1,$(BSUB_WRAP)),$(BSUB_SHELL) $(BSUB_SHELL_OPTS) 'cd "$(CURDIR)" && $(MAKE) sim $(MAKEOVERRIDES)',$(MAKE) -C "$(CURDIR)" sim $(MAKEOVERRIDES))

.PHONY: regress_bsub
regress_bsub:
	$(BSUB) $(BSUB_OPTS) $(if $(filter 1,$(BSUB_WRAP)),$(BSUB_SHELL) $(BSUB_SHELL_OPTS) 'cd "$(CURDIR)" && $(MAKE) regress $(MAKEOVERRIDES)',$(MAKE) -C "$(CURDIR)" regress $(MAKEOVERRIDES))

.PHONY: doctor_bsub
doctor_bsub:
	$(BSUB) $(BSUB_OPTS) $(if $(filter 1,$(BSUB_WRAP)),$(BSUB_SHELL) $(BSUB_SHELL_OPTS) 'cd "$(CURDIR)" && $(MAKE) doctor $(MAKEOVERRIDES)',$(MAKE) -C "$(CURDIR)" doctor $(MAKEOVERRIDES))

.PHONY: cov_bsub
cov_bsub:
	$(BSUB) $(BSUB_OPTS) $(if $(filter 1,$(BSUB_WRAP)),$(BSUB_SHELL) $(BSUB_SHELL_OPTS) 'cd "$(CURDIR)" && $(MAKE) cov $(MAKEOVERRIDES)',$(MAKE) -C "$(CURDIR)" cov $(MAKEOVERRIDES))

.PHONY: clean
clean::
	rm -rf sim_build simv* csrc ucli.key verdiLog*
	rm -rf $(CURDIR)/__pycache__ $(ROOT_DIR)/tb/__pycache__ $(ROOT_DIR)/tests/__pycache__ $(ROOT_DIR)/*.pyc

.PHONY: clean_out
clean_out:
	rm -rf $(OUT_ROOT)/* regression_out/*
	rm -rf *.fsdb *.vcd *.vpd *.log coverage.yml results.xml cm.vdb cov_html doctor*.log doctor*.txt

.PHONY: clean_artifacts
clean_artifacts:
	@echo "Performing local sim cleanup..."
	@rm -rf $(SIM_BUILD)/* $(OUT_ROOT)/* regression_out/*
	@for d in tb tests rtl filelists; do \
	  if [ -d "$(ROOT_DIR)/$$d" ]; then \
	    find "$(ROOT_DIR)/$$d" -name "__pycache__" -exec rm -rf {} +; \
	    find "$(ROOT_DIR)/$$d" -name "*.pyc" -delete; \
	  fi; \
	done
	@rm -f *.fsdb *.vcd *.vpd *.log coverage.yml results.xml cm.vdb cov_html doctor*.log doctor*.txt

.PHONY: distclean
distclean:
	@$(MAKE) clean
	@$(MAKE) clean_out

.PHONY: regress
REGR_COV_DAT_FILE_ARG :=
ifneq ($(filter command\ line environment,$(origin COV_DAT_FILE)),)
  REGR_COV_DAT_FILE_ARG := REGR_COV_DAT_FILE="$(COV_DAT_FILE)"
endif
regress:
	PYTHON_BIN="$(PYTHON_BIN)" \
	REGR_MODULES="$(REGR_MODULES)" \
	REGR_SEEDS="$(REGR_SEEDS)" \
	REGR_OUT="$(REGR_OUT)" \
	REGR_REBUILD="$(REGR_REBUILD)" \
	REGR_SAVE_LOGS="$(REGR_SAVE_LOGS)" \
	$(REGR_COV_DAT_FILE_ARG) \
	OUT_ROOT="$(OUT_ROOT)" \
	TOPLEVEL="$(TOPLEVEL)" \
	RTL_FILELISTS="$(RTL_FILELISTS)" \
	TB_SOURCES="$(TB_SOURCES)" \
	MAX_CREDIT="$(MAX_CREDIT)" \
	FIFO_DEPTH="$(FIFO_DEPTH)" \
	TOP_PARAMS="$(TOP_PARAMS)" \
	WAVES="$(WAVES)" \
	WAVE_SCOPE="$(WAVE_SCOPE)" \
	DEBUG="$(DEBUG)" \
	COV="$(COV)" \
	./run_regression.sh

.PHONY: suite
suite:
	PYTHON_BIN="$(PYTHON_BIN)" \
	REGR_SEEDS="$(REGR_SEEDS)" \
	REGR_OUT="$(REGR_OUT)" \
	./run_template_suite.sh
