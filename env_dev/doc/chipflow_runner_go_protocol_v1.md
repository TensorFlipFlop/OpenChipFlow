# ChipFlow Runner <-> TUI 协议（v1）

更新时间：2026-03-11

目标：把 OpenChipFlow 的“文件入口 / 文件出口”收敛成两个稳定契约：

- `request manifest`
- `ui manifest`

这样 Python TUI、Go TUI 和后续其他前端都不需要再自己拼环境变量或猜测产物路径。

---

## 1. 设计结论

旧方式的问题：

- `run all`、`handoff_intake`、`incremental_verify_ready` 的输入方式不统一
- handoff 模式依赖环境变量，不适合 TUI 表单和多会话管理
- `ui_manifest.json` 只有 run 级摘要，不足以表达输入文件、主产物和下一步动作

v1 现在统一为：

1. TUI 生成 `request manifest`
2. runner 执行 `./chipflow request --request-manifest <file>`
3. runner 输出 `artifacts/runs/<run_id>/ui_manifest.json`
4. TUI 只消费 `ui_manifest.json`

---

## 2. 传输方式

- 进程模型：Go/Python TUI 启动 `python3 scripts/runner.py ...`
- stdout：
  - 普通模式输出单次 JSON / 文本结果
  - `--event-stream jsonl` 时输出结构化事件流
- stderr：人类可读日志

退出码：

- `0` 成功
- `2` 配置错误
- `3` stage 不存在
- `4` 执行失败，或 quota guard 拒绝
- `130` 用户中断

机读协议文件：

- [`artifacts/protocol/runner_protocol_v1.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/artifacts/protocol/runner_protocol_v1.json)
- [`config/schemas/runner_request_manifest.schema.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/config/schemas/runner_request_manifest.schema.json)
- [`config/schemas/runner_ui_manifest.schema.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/config/schemas/runner_ui_manifest.schema.json)

---

## 3. 顶层命令

最小命令集：

- `list`
- `run`
- `stage`
- `doctor`
- `request`
- `status`
- `log`
- `stop`

新增关键命令：

```bash
./chipflow request --request-manifest artifacts/protocol/examples/request_spec_flow.json
```

这个命令让前端不需要理解 `spec_flow` / `handoff_intake` / `incremental_verify_ready` 背后分别映射到哪个 flow，只要提交请求即可。

---

## 4. 输入契约：Request Manifest

`request manifest` 是 TUI 写给 runner 的文件入口描述。

schema：

- [`runner_request_manifest.schema.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/config/schemas/runner_request_manifest.schema.json)

核心字段：

```json
{
  "schema_version": "runner_request_manifest/v1",
  "session_id": "session_...",
  "mode": "spec_flow | handoff_intake | incremental_verify_ready",
  "execution": {
    "mode": "plan | all",
    "dry_run": false
  },
  "runtime": {
    "model": "openai-codex/gpt-5.3-codex",
    "variant": "medium",
    "thinking": "high"
  },
  "inputs": {
    "spec_source": {
      "path": "...",
      "import_mode": "snapshot"
    }
  }
}
```

### 4.1 输入导入策略

每个路径输入都支持两种模式：

- `reference`
  - 直接引用原文件
  - 快，但会依赖外部路径稳定性
- `snapshot`
  - 导入到 `cocotb_ex/artifacts/sessions/<session_id>/inputs/...`
  - 更适合 TUI 和多会话隔离

### 4.2 执行深度 vs dry-run

- `execution.mode` 负责选择真实 flow 深度，例如 `spec_flow` 的 `plan` 或 `all`
- `execution.dry_run` 只负责“预演不执行”
- 这两个开关必须独立；只有显式打开 dry-run 时，runner 和 downstream pipeline 才会进入 dry-run

另外，`spec_source` 支持 inline text 导入，runner 会物化成会话内文件。

### 4.2 三种模式的文件入口

#### `spec_flow`

适用场景：从 `spec.md` 出发跑 `plan` 或 `all`。

要求：

- 必需：`inputs.spec_source`
- 执行：`execution.mode = plan | all`

推荐做法：

- TUI 导入 spec 时默认用 `snapshot`
- 不要再覆盖共享的 `specs/inbox/spec.md`

样例：

- [`request_spec_flow.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/artifacts/protocol/examples/request_spec_flow.json)

#### `handoff_intake`

适用场景：检查上游 AI handoff 是否合格。

要求：

- 必需：`inputs.handoff_root` 或 `inputs.handoff_manifest`
- 可选：`inputs.target_state`

推荐做法：

- handoff 目录默认优先 `snapshot`
- 若已有稳定 `handoff_manifest.json`，可直接 `reference`

样例：

- [`request_handoff_intake.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/artifacts/protocol/examples/request_handoff_intake.json)

#### `incremental_verify_ready`

适用场景：handoff 已经达到 `verify_ready`，直接进入验证闭环。

要求：

- 必需：`inputs.handoff_manifest`
- 可选：`inputs.backend_policy`

样例：

- [`request_incremental_verify_ready.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/artifacts/protocol/examples/request_incremental_verify_ready.json)

### 4.3 Runner 的物化结果

runner 解析 request 后，会在会话目录生成：

- `cocotb_ex/artifacts/sessions/<session_id>/request.normalized.json`

这个文件是“已解析后的真实执行请求”，便于审计和重放。

---

## 5. 输出契约：UI Manifest

`ui manifest` 是 runner 写给 TUI 的统一出口。

schema：

- [`runner_ui_manifest.schema.json`](/home/user/.openclaw/workspace/projects/open-chip-flow/config/schemas/runner_ui_manifest.schema.json)

输出位置：

- `artifacts/runs/<run_id>/ui_manifest.json`

核心字段：

```json
{
  "schema_version": "runner_ui_manifest/v1",
  "run_id": "run_...",
  "session_id": "session_...",
  "mode": "handoff_intake",
  "request_manifest": "/abs/path/request.json",
  "request_artifacts": [],
  "input_artifacts": [],
  "primary_artifacts": [],
  "secondary_artifacts": [],
  "log_files": [],
  "next_actions": []
}
```

### 5.1 产物分层

- `request_artifacts`
  - request manifest
  - normalized request
- `input_artifacts`
  - runner 实际消耗的输入文件或目录
- `primary_artifacts`
  - 当前模式下最重要、最适合展示给用户的结果
- `secondary_artifacts`
  - 补充文件
- `log_files`
  - run 级日志路径
- `next_actions`
  - 可供 TUI 直接渲染成按钮或快捷动作

每个 artifact 至少带：

- `id`
- `label`
- `kind`
- `path`
- `abs_path`
- `exists`
- `previewable`
- `copyable`

### 5.2 三种模式的主要出口

#### `spec_flow`

主要出口：

- normalized spec
- `reqs.md`
- `testplan.md`
- RTL / filelist / TB / test module
- `verify.md`

补充出口：

- `case_schedule.json`
- `req_trace_matrix.md`
- `req_trace_matrix.json`

#### `handoff_intake`

主要出口：

- `handoff_inventory.json`
- `handoff_audit.json`
- `handoff_gap_report.md`
- `handoff_repair_prompt.txt`
- `handoff_manifest.candidate.json`（若可推断）

#### `incremental_verify_ready`

主要出口：

- `handoff_context.json`
- `case_schedule.json`
- `req_trace_matrix.md`
- `req_trace_matrix.json`
- `verify.md`

---

## 6. 事件流

`--event-stream jsonl` 现在已经包含 `session_id`，便于 TUI 在多会话模式下绑定到正确窗口。

示例：

```json
{"type":"run_started","run_id":"run_...","session_id":"session_...","command":"request","effective_command":"run","target":"handoff_intake","mode":"handoff_intake","dry_run":false}
{"type":"stage_started","run_id":"run_...","session_id":"session_...","stage":"handoff_intake"}
{"type":"cmd_finished","run_id":"run_...","session_id":"session_...","stage":"handoff_intake","name":"handoff_intake","rc":0,"duration_s":1.2}
{"type":"run_finished","run_id":"run_...","session_id":"session_...","target":"flow:handoff_intake","rc":0}
```

关键字段：

- `session_id`
- `effective_command`
- `mode`
- `target`

---

## 7. TUI 集成建议

TUI 不应再把自己做成“runner 参数拼接器”，而应做成：

1. 表单收集输入
2. 生成 `request manifest`
3. 调用 `./chipflow request --request-manifest ...`
4. 读取 `ui_manifest.json`
5. 仅根据 `primary_artifacts / secondary_artifacts / next_actions` 展示结果

这样可以同时解决：

- 三种模式入口不一致
- 文件入口难以扩展
- 产物展示逻辑分散
- 多 terminal / 多 session 的隔离问题

---

## 8. 当前限制

当前已经实现：

- `request manifest` 解析与物化
- `ui manifest` 富化
- `session_id` 贯穿 run 事件与结果
- `spec_flow` / `handoff_intake` / `incremental_verify_ready` 三模式请求入口

当前仍未完全解决：

- 同 repo 下所有真实可写运行的全链路 namespacing
- `handoff_root` 目录快照与 handoff 内相对路径在所有场景下的完全兼容
- TUI 侧基于 schema 的完整表单和结果面板
