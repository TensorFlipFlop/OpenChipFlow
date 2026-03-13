# ========= 基本设置 =========
ROOT_DIR := $(abspath $(CURDIR)/..)

TOPLEVEL_LANG      = verilog
SIM                = vcs
TOPLEVEL           ?= tb_top

# cocotb 2.x 推荐变量（避免上游 Makefile 的 deprecation warning）
COCOTB_TEST_MODULES ?= tests.test_adder
COCOTB_TESTCASE ?=

# 兼容旧变量（MODULE/TESTCASE）：若使用旧变量，则映射到 COCOTB_* 并清空旧变量
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

# 默认目标：直接跑仿真（与 README 中 `make` 用法一致）
.DEFAULT_GOAL := sim

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
# 示例：make W=16 -> 默认传 -pvalue+<TOPLEVEL>.W=16
W ?= 8
TOP_PARAMS ?= -pvalue+$(TOPLEVEL).W=$(W)
COMPILE_ARGS      += $(TOP_PARAMS)

# ========= 波形（FSDB）=========
# 目标环境默认支持 FSDB/Verdi；可用 WAVES=0 关闭波形提升速度
WAVES ?= 1
FSDB_FILE ?= $(RUN_DIR)/waves.fsdb

# 波形范围：默认全量；WAVE_SCOPE=dut 只 dump tb_top.dut（更小更快）
WAVE_SCOPE ?= full
ifeq ($(WAVE_SCOPE),dut)
  SIM_ARGS += +DUT_ONLY
endif

# Verdi/PLI 自动探测（也可手动指定 VERDI_HOME 或 VERDI_PLI_TAB）
NOVAS_HOME ?=
VERDI_HOME ?= $(NOVAS_HOME)
VERDI_HOME ?= $(shell verdi_bin=$$(command -v verdi 2>/dev/null || true); if [ -n "$$verdi_bin" ]; then dirname $$(dirname "$$verdi_bin"); fi)
VERDI_PLI_TAB ?= $(firstword $(wildcard $(VERDI_HOME)/share/PLI/VCS/*/verdi.tab))
VERDI_PLI_TAB ?= $(firstword $(wildcard $(VERDI_HOME)/share/PLI/VCS/*/novas.tab))
VERDI_PLI_LIB ?= $(firstword $(wildcard $(dir $(VERDI_PLI_TAB))pli.a))
VERDI_PLI_LIB ?= $(firstword $(wildcard $(dir $(VERDI_PLI_TAB))pli.so))

ifeq ($(WAVES),1)
  ifneq ($(strip $(VERDI_PLI_TAB)),)
    ifneq ($(strip $(VERDI_PLI_LIB)),)
      COMPILE_ARGS += -P $(VERDI_PLI_TAB) $(VERDI_PLI_LIB)
    else
      COMPILE_ARGS += -P $(VERDI_PLI_TAB)
    endif
  endif
  COMPILE_ARGS    += +define+FSDB
  SIM_ARGS        += +FSDB +fsdbfile=$(FSDB_FILE)
endif

# 生成 KDB/全量调试信息（Verdi 深度调试用）；DEBUG=0 可加速编译
DEBUG ?= 1
ifeq ($(DEBUG),1)
  COMPILE_ARGS    += -kdb -debug_access+all
endif

# ========= 日志/输出控制 =========
# QUIET=1 降低 VCS 编译输出；COMPILE_LOG/SIM_LOG 可重定向日志到文件
QUIET ?= 0
ifeq ($(QUIET),1)
  COMPILE_ARGS    += -q
endif

COMPILE_LOG ?=
ifneq ($(COMPILE_LOG),)
  COMPILE_ARGS    += -l $(abspath $(COMPILE_LOG))
endif

SIM_LOG ?=
ifneq ($(SIM_LOG),)
  SIM_ARGS        += -l $(abspath $(SIM_LOG))
endif

# ========= 覆盖率（VCS code coverage）=========
# COV=1 开启；COV_TYPES 可配置
COV ?= 1
COV_TYPES ?= line+cond+tgl
# 覆盖率默认按 case 归档（同一 case 可用不同 seed 反复跑并累积到同一个 cm.vdb）
COV_DIR ?= $(CASE_DIR)/cov/cm.vdb
COV_REPORT_DIR ?= $(CASE_DIR)/cov/cov_html
# 使用绝对路径避免 cocotb 的 build/run 目录不同导致 cm.vdb 被拆分生成，
# 从而出现 urg 报错：[UCAPI-DNYL] Design not yet loaded
COV_DIR_ABS := $(abspath $(COV_DIR))
COV_REPORT_DIR_ABS := $(abspath $(COV_REPORT_DIR))
ifeq ($(COV),1)
  EXTRA_ARGS      += -cm $(COV_TYPES) -cm_dir $(COV_DIR_ABS)
  # VCS runtime 也支持 -cm_dir；显式传入，确保与编译期一致
  SIM_ARGS        += -cm_dir $(COV_DIR_ABS)
endif

.PHONY: cov
cov:
	@if [ "$(COV)" != "1" ]; then \
	  echo "COV=0, skip urg."; \
	elif ! command -v urg >/dev/null 2>&1; then \
	  echo "ERROR: urg not found (check VCS installation/PATH)."; exit 1; \
	elif [ ! -d "$(COV_DIR_ABS)" ]; then \
	  echo "ERROR: $(COV_DIR_ABS) not found. Run 'make' (or 'make sim') with COV=1 first."; exit 1; \
	else \
	  urg -dir $(COV_DIR_ABS) -report $(COV_REPORT_DIR_ABS) || { \
	    echo "ERROR: urg failed. If you see '[UCAPI-DNYL] Design not yet loaded', it's usually because -cm_dir was relative and VCS wrote design/tests into different directories."; \
	    echo "Hint: make clean_out && make sim COV_DIR=$(COV_DIR_ABS) && make cov COV_DIR=$(COV_DIR_ABS)"; \
	    echo "Also check duplicates: find . -maxdepth 3 -type d -name cm.vdb -print"; \
	    exit 1; \
	  }; \
	  echo "Coverage report -> $(COV_REPORT_DIR_ABS)/index.html"; \
	fi

# ========= 运行前自检（提升离线环境一次成功率）=========
.PHONY: precheck
precheck:
	@mkdir -p "$(RUN_DIR)" "$(SIM_BUILD)"
	@mkdir -p "$(dir $(abspath $(FSDB_FILE)))"
	@mkdir -p "$(dir $(abspath $(COCOTB_RESULTS_FILE)))"
	@mkdir -p "$(dir $(COV_DIR_ABS))"
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
		@lib=$$($(COCOTB_CONFIG) --lib-name-path vpi vcs 2>/dev/null || $(COCOTB_CONFIG_FALLBACK) --lib-name-path vpi vcs 2>/dev/null || true); \
			  test -n "$$lib" && test -f "$$lib" || { \
			    echo "ERROR: cocotb VPI library for VCS not found: $$lib"; \
			    echo "Hint: check cocotb installation or PYTHONPATH; run: $(COCOTB_CONFIG) --lib-name-path vpi vcs"; \
			    exit 1; \
			  }
	@command -v vcs >/dev/null 2>&1 || { echo "ERROR: vcs not found in PATH."; exit 1; }
	@for fl in $(RTL_FILELISTS); do \
	  test -f "$$fl" || { echo "ERROR: RTL filelist not found: $$fl"; exit 1; }; \
	done
	@for f in $(TB_SOURCES); do \
	  test -f "$$f" || { echo "ERROR: TB_SOURCES not found: $$f (set TOPLEVEL or TB_SOURCES)"; exit 1; }; \
	done
	@$(PYTHON_BIN) $(CURDIR)/expand_filelists.py --check --sources $(RTL_FILELISTS) >/dev/null
	@if [ "$(WAVES)" = "1" ]; then \
	  if [ -z "$(VERDI_PLI_TAB)" ]; then \
	    echo "ERROR: WAVES=1 but VERDI_PLI_TAB not found."; \
	    echo "Hint: set VERDI_HOME or VERDI_PLI_TAB, or run: make WAVES=0"; \
	    exit 1; \
	  fi; \
	  test -f "$(VERDI_PLI_TAB)" || { echo "ERROR: VERDI_PLI_TAB not found on disk: $(VERDI_PLI_TAB)"; exit 1; }; \
	  if [ -z "$(VERDI_PLI_LIB)" ]; then \
	    echo "ERROR: WAVES=1 but VERDI_PLI_LIB not found (expected pli.a/pli.so near VERDI_PLI_TAB)."; \
	    echo "Hint: set VERDI_PLI_LIB=/path/to/pli.a (or pli.so), or run: make WAVES=0"; \
	    exit 1; \
	  fi; \
	  test -f "$(VERDI_PLI_LIB)" || { echo "ERROR: VERDI_PLI_LIB not found on disk: $(VERDI_PLI_LIB)"; exit 1; }; \
	fi

# ========= 随机种子/用例数（传给 tests）=========
export SEED ?= 42
export N    ?= 200

# 允许在未配置 VCS 的机器上仍能执行 `make doctor/clean/...` 做排查
SKIP_COCOTB_GOALS := doctor clean clean_out distclean verdi cov sim_bsub regress_bsub doctor_bsub cov_bsub
ifneq ($(MAKECMDGOALS),)
  NEED_COCOTB_GOALS := $(filter-out $(SKIP_COCOTB_GOALS),$(MAKECMDGOALS))
else
  NEED_COCOTB_GOALS := all
endif

ifneq ($(NEED_COCOTB_GOALS),)
include $(shell $(COCOTB_CONFIG) --makefiles 2>/dev/null || $(COCOTB_CONFIG_FALLBACK) --makefiles 2>/dev/null)/Makefile.sim

# 确保仿真/编译前先做一次 precheck（避免内网环境难定位错误）
$(SIM_BUILD)/simv: precheck
$(COCOTB_RESULTS_FILE): precheck
endif

.PHONY: verdi
verdi:
	@command -v verdi >/dev/null 2>&1 || { echo "ERROR: verdi not found in PATH."; exit 1; }
	@test -f "$(FSDB_FILE)" || { echo "ERROR: $(FSDB_FILE) not found. Run 'make' with WAVES=1 first."; exit 1; }
	@echo "Open $(FSDB_FILE) with verdi..."
	verdi -ssf $(FSDB_FILE) &

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
	FSDB_FILE="$(FSDB_FILE)" \
	DEBUG="$(DEBUG)" \
	COV="$(COV)" \
	COV_TYPES="$(COV_TYPES)" \
	COV_DIR="$(COV_DIR)" \
	VERDI_HOME="$(VERDI_HOME)" \
	VERDI_PLI_TAB="$(VERDI_PLI_TAB)" \
	VERDI_PLI_LIB="$(VERDI_PLI_LIB)" \
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
	rm -rf $(OUT_ROOT) regression_out
	rm -rf *.fsdb *.vcd *.vpd *.log coverage.yml results.xml cm.vdb cov_html doctor*.log doctor*.txt

.PHONY: distclean
distclean:
	@$(MAKE) clean
	@$(MAKE) clean_out

.PHONY: regress
REGR_COV_DIR_ARG :=
ifneq ($(filter command\ line environment,$(origin COV_DIR)),)
  REGR_COV_DIR_ARG := REGR_COV_DIR="$(COV_DIR)"
endif
regress:
	PYTHON_BIN="$(PYTHON_BIN)" \
	REGR_MODULES="$(REGR_MODULES)" \
	REGR_SEEDS="$(REGR_SEEDS)" \
	REGR_OUT="$(REGR_OUT)" \
	REGR_REBUILD="$(REGR_REBUILD)" \
	REGR_SAVE_LOGS="$(REGR_SAVE_LOGS)" \
	$(REGR_COV_DIR_ARG) \
	TOPLEVEL="$(TOPLEVEL)" \
	RTL_FILELISTS="$(RTL_FILELISTS)" \
	TB_SOURCES="$(TB_SOURCES)" \
	W="$(W)" \
	TOP_PARAMS="$(TOP_PARAMS)" \
	WAVES="$(WAVES)" \
	WAVE_SCOPE="$(WAVE_SCOPE)" \
	DEBUG="$(DEBUG)" \
	QUIET="$(QUIET)" \
	COV="$(COV)" \
	COV_TYPES="$(COV_TYPES)" \
	VERDI_HOME="$(VERDI_HOME)" \
	VERDI_PLI_TAB="$(VERDI_PLI_TAB)" \
	VERDI_PLI_LIB="$(VERDI_PLI_LIB)" \
	./run_regression.sh

.PHONY: suite
suite:
	PYTHON_BIN="$(PYTHON_BIN)" \
	REGR_SEEDS="$(REGR_SEEDS)" \
	REGR_OUT="$(REGR_OUT)" \
	./run_template_suite.sh
