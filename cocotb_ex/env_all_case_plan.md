# Feature Plan: Testplan Sequential Iteration Dispatcher

## 1. 目标 (Goal)

实现对 `testplan.md` 中定义的所有测试用例 (Case 001, 002...) 的自动化逐个迭代收敛。
当前环境只能运行配置固定的单个 Case 或全量回归。本 Feature 将引入“调度器”逻辑，使 Pipeline 能够智能地解析测试计划，并按顺序对每个 Case 调用 Orchestrator 进行“运行 -> 修复 -> 通过”的闭环操作。

## 2. 核心架构设计 (Architecture)

采用 **"Dynamic Dispatcher Role"** 方案。利用现有的 `run_pipeline.py` 架构，增加一个前置的调度角色，负责生成执行序列。

### 2.1 新增 Role: `testplan_dispatcher`

*   **位置**: `config.json` 中的 `execution_order`，位于 `code_formatter` 之后，`sim_runner` 之前。
*   **AI Engine**: `codex` (擅长逻辑与结构化数据处理) 或 `claude`。
*   **输入**:
    *   `specs/out/testplan.md`: 包含测试用例列表。
    *   `specs/out/reqs.md`: 需求文档 (可选，用于上下文)。
*   **输出**:
    *   `artifacts/case_schedule.json`: 一个结构化的任务列表，包含需要运行的所有 Case ID 及其对应的测试指令。
    *   *(可选)* `artifacts/run_schedule.sh`: 一个可直接执行的 Shell 脚本，串行调用 `make verify CASE=...`。

### 2.2 改造 `run_pipeline.py` (支持动态执行)

目前的 `run_pipeline.py` 是按 `config.json` 静态顺序执行的。为了支持动态调度，需要增强 Runner 的能力：

*   **功能**: 支持从上一步 (`testplan_dispatcher`) 生成的 `case_schedule.json` 中读取任务列表。
*   **逻辑**:
    1.  检测到 `testplan_dispatcher` 完成。
    2.  读取 `artifacts/case_schedule.json`。
    3.  遍历 JSON 中的每个 Case。
    4.  对每个 Case，动态实例化一个 `sim_runner` 任务（复用 Orchestrator 逻辑），并将 `case_id` 和 `testcase` 参数注入。
    5.  串行执行，直到列表结束。

### 2.3 状态流转 (Workflow)

1.  **Spec/Testplan Gen**: 生成 `testplan.md` (已有)。
2.  **Code Gen & Format**: 生成 RTL/TB 并格式化 (已有)。
3.  **Dispatcher (New)**:
    *   读取 `testplan.md`。
    *   解析出所有 Testcase (如 `run_basic`, `test_fifo_full`, `test_credit_error` 等)。
    *   生成 `case_schedule.json`。
4.  **Sequential Execution (New Logic)**:
    *   **Loop Case 1**: `make verify CASE=run_basic` -> Fail -> Orchestrator Fix -> Pass.
    *   **Loop Case 2**: `make verify CASE=test_fifo_full` -> Pass.
    *   **Loop Case 3**: `make verify CASE=test_credit_error` -> Fail -> Fix -> Pass.
    *   ...
5.  **Final Regression**: 运行一次全量回归 `regress_runner`，确保之前的修复没有引入回归错误。

## 3. 详细实施步骤 (Implementation Steps)

### Step 1: 创建 Dispatcher Prompt
*   文件: `cocotb_ex/ai_cli_pipeline/prompts/dispatch_testplan.txt`
*   内容: 指示 AI 读取 Markdown 表格/列表，提取 Testcase Name，并输出为 JSON 格式。

### Step 2: 更新 Pipeline Config
*   文件: `cocotb_ex/ai_cli_pipeline/config.json`
*   修改:
    *   添加 `testplan_dispatcher` role。
    *   调整 `execution_order`。

### Step 3: 增强 `run_pipeline.py`
*   修改: 增加对 `dynamic_loop` 或 `schedule_file` 的支持。
*   逻辑: 当 Role 配置了 `drive_loop_from_file` 时，读取该文件，并为文件中的每一项重复执行指定的 Sub-Role (即 `sim_runner`)。

### Step 4: 验证
*   运行 `make debug` 确认调度逻辑。
*   运行 `make pipeline` 观察是否逐个 Case 运行。

## 4. 数据结构示例 (Data Structures)

**`case_schedule.json`**:
```json
[
  {
    "case_id": "T_001_BASIC",
    "testcase": "run_basic",
    "description": "Basic smoke test"
  },
  {
    "case_id": "T_002_FIFO_FULL",
    "testcase": "test_fifo_full",
    "description": "Verify backpressure when FIFO is full"
  }
]
```

## 5. 优势 (Benefits)

*   **精细化收敛**: 不会因为一个 Case 难修而阻塞所有测试，也不会因为一次性修太多导致 AI 上下文溢出。
*   **可观测性**: 清晰地看到每个 Case 的 Pass/Fail 状态和修复过程。
*   **复用性**: 复用了强大的 Orchestrator，不需要重新写修复逻辑，只是在上层加了一个循环调度。
