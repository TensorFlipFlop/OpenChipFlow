# OpenChipFlow Go BubbleTea TUI 使用说明

更新时间：2026-03-11

## 启动

```bash
cd /home/user/.openclaw/workspace/projects/open-chip-flow

# 直接启动 Go 版本
./chipflow-tui-go

# 指定界面语言（en / zh）
./chipflow-tui-go --lang zh

# 兼容入口（默认 Python），加 --go 强制 Go 前端
./chipflow-tui --go

# 也可给 Python / Go TUI 统一指定语言
CHIPFLOW_TUI_LANG=en ./chipflow-tui
CHIPFLOW_TUI_LANG=zh ./chipflow-tui-go

# 也可用环境变量切换默认前端
CHIPFLOW_TUI_FRONTEND=go ./chipflow-tui
```

## 快捷键

- `/`：命令面板主快捷键（支持 `mode:` / `tool:` / `advanced:` 过滤）
- `Ctrl+K`：命令面板兼容快捷键（保留，但不再作为主推荐）
- `?`：打开快捷键帮助面板；再按一次 `?` 或 `Esc` 关闭
- `↑/↓`：选择命令
- `Enter`：打开模式表单，或对工具命令执行二次确认
- `Esc`：仅关闭表单 / overlay / palette / confirm，不再直接退出
- `l`：切换中/英文界面标签
- `Shift+D`：切换 dry-run
- Go TUI 默认是 `dry-run=OFF`；只有显式按 `Shift+D` 才会切到预演模式
- `Shift+↑/↓`：在输出区上下滚动日志
- `y`：在当前可复制的提示词视图复制当前提示词
- `x` / `Ctrl+X`：停止当前任务
- `c`：清理输出区
- `v`：右侧视图切换
  - 普通模式：`LOGS / STDOUT / STDERR / RESULTS / INPUTS / PROMPTS`
  - `Handoff Intake`：`LOGS / STDOUT / STDERR / BASIS / REQUIREMENTS / REVIEW / FEEDBACK`
- `r`：重跑上次任务（rerun last）
- `Shift+F`：失败 stage 快速续跑（如果能定位失败阶段）
- `Ctrl+O`：模型面板（model）
- `Ctrl+T`：variant 面板（先选 model；variant 跟随 model 家族变化）
- `Ctrl+S`：stage 快切面板
- `Ctrl+C` 连按 3 次：强制退出；若当前有任务在跑，会先停止该任务再退出
- `q`：不再退出，只提示使用 `Ctrl+C` 连按 3 次退出
- `?` 帮助面板与 `RESULTS / INPUTS` 里的长路径都改为自动换行显示，不再用 `...` 截断

## 主界面结构

左栏已与 Python TUI 对齐，固定分为三段：

- `Modes`
  - `Spec Flow`
  - `Handoff Intake`
  - `Verify-Ready Handoff`
- `Tools`
  - `Environment Check`
  - `List Flows / Stages`
- `Advanced`
  - `Direct Flow Run`
  - `Stage Quick Run`
  - `Rerun Failed Stage`

说明性 stage 不再混在左栏控制项里，而是随着当前 mode 显示在中栏 `OUTLINE` 区域：

- `Spec Flow`
  - `Precheck -> Plan -> Generate RTL/TB -> Prepare Verification -> Smoke -> Verify -> Regress -> Deliver`
  - `execution_mode = plan | all` 只控制流程深度
- `Handoff Intake`
  - `Discover Inputs -> Audit Handoff -> Emit Feedback`
  - 该模式先做 host-side contract audit/materialize；当启用 semantic review 时，会在 workflow 内部追加 AI reviewer 与 acceptance gate
- `Verify-Ready Handoff`
  - `Validate Handoff -> Prepare Verification -> Quality Gates -> Smoke -> Verify -> Regress -> Compliance`

选择 `Modes` 下的条目后按 `Enter`，会打开 request form。Go TUI 现在会：

1. 生成 `request manifest`
2. 调用 `./chipflow request --request-manifest ...`
3. 在右侧语义视图中读取 `ui_manifest.json`

`Handoff Intake` 的 request form 额外支持：

- `Preview Intake Contract`
  - 打开执行前的 OpenChipFlow handoff 合同提示词
- `Copy Intake Contract`
  - 直接复制交接要求给前期 AI
- `Source Requirements Folder`
  - 原始需求参考目录
- `Content Review Policy`
  - `required | auto | off`

语义规则：

- `plan` 和 `all` 是 `Spec Flow` 的执行深度，不是 dry-run 开关
- dry-run 只由 `Shift+D` 或 request manifest 里的 `execution.dry_run` 控制
- 当本次运行是 dry-run 时，结果面板会把产物标成 `preview`
- quota guard 规则：
  - `Handoff Intake` 默认跳过外层 quota guard。
  - 当 `Content Review Policy` 不是 `off` 且 source context 可用时，workflow 会在 semantic reviewer 前执行 stage-level quota gate。
  - `Spec Flow(plan/all)` 与 `Verify-Ready Handoff` 仍保留 quota guard。

request form 中的路径字段：

- `spec_source`
- `handoff_root`
- `handoff_manifest`
- `source_requirements_root`

在编辑状态下按 `Tab` 可做路径补全。相对路径默认基于仓库根目录解析，绝对路径和 `~/...` 也支持。
若存在多个匹配项，表单会在下方显示多行候选列表，并尽量占满可用高度，而不是只给一行短摘要。

主界面可见入口：
- 顶部标题栏会固定显示 `? Help`、`/ Palette`
- 标题栏与模式/命令标签支持 `l` 热切换中英文
- 底部状态栏会固定显示 `[?:HELP]`
- 中栏 `KEYS` 首行也会显示 `? help`

帮助面板优先级：
- `?` 打开后，第一组 `ESSENTIAL` 会优先显示 `Shift+D`
- 即使小窗口裁剪下半部分，最常用键仍会保留在帮助面板顶部

输出区说明：
- 普通模式下，右侧仍显示 `LOGS / STDOUT / STDERR / RESULTS / INPUTS / PROMPTS`
- `Handoff Intake` 下，右侧改为语义视图：
  - `BASIS`
    - 显示 `source_requirements_root`、`handoff_source_index`
  - `REQUIREMENTS`
    - 显示 `handoff_requirements_prompt.txt`
  - `REVIEW`
    - 显示 `handoff_contract_audit.json` / `handoff_semantic_review.json` / `handoff_acceptance.json` 摘要
  - `FEEDBACK`
    - 显示 `handoff_contract_repair_prompt.txt` / `handoff_semantic_repair_prompt.txt`
- 在 `Handoff Intake` 中：
  - `y` 在 `REQUIREMENTS` 视图复制交接要求提示词
  - `y` 在 `FEEDBACK` 视图复制当前优先 repair prompt
  - `o` 将当前输出视图展开成宽视图，适合看长日志、长路径和完整 prompt
  - `BASIS` 不再与系统反馈混在同一个 `PROMPTS` 视图里
- 当 `Handoff Intake` 返回 `needs_repair` 时，Go TUI 会自动切到 `FEEDBACK`
- 当 `Handoff Intake` 通过时，Go TUI 会自动切到 `REVIEW`
- 当滚离底部时，输出标题会显示 `scroll=<n>`，表示当前向上翻看的行数

增量两阶段建议：

1. 先在 `Handoff Intake` 里预览/复制 requirements prompt，回喂前期 AI。
2. 让前期 AI 严格按以下布局组织 handoff 包：
   - `source_requirements/...`
   - `baseline_summary.md`
   - `compat_constraints.md`
   - `changed_files_allowlist.yaml`
   - `spec.md`
   - `reqs.md` 或 `delta_spec.md`
   - `testplan.md` 或 `testplan_delta.md`
   - `rtl/...`
   - `filelists/...`
   - `tb/hdl/...`
   - `tb/*.py`
   - `tests/*.py`
3. intake 通过后，直接使用同 session 下的 `handoff_manifest.materialized.json` 进入 `Verify-Ready Handoff`。

模型 / variant 规则：
- 先用 `Ctrl+O` 选择具体 model，再用 `Ctrl+T` 选择 variant。
- `codex` 家族：variant 固定提供 `Low / Medium / High / Extra High`，默认 `High`。
- `gemini` 家族：没有单独 variant；切到 Gemini model 后，状态区会显示 `Variant: n/a`。
- `opencode` 家族：variant 继续使用原生 `Low / Medium / High`。

## 回归验证

```bash
# Python TUI smoke
make tui-smoke

# Go TUI smoke
make tui-go-smoke
```

Go TUI smoke 会做：启动、命令面板过滤、request form 打开/编辑/路径补全/提交、结果视图切换、overlay 切换、dry-run 切换、rerun last、退出稳定性检查。
若缺少 `pexpect`，smoke 会输出 `SKIP`，避免把“测试依赖未安装”误判为 Go TUI 本身失效。

## 兼容策略

- `chipflow-tui` 默认保持 Python TUI（稳态）。
- Go TUI 通过 `--go` 或 `CHIPFLOW_TUI_FRONTEND=go` 显式启用。
- `chipflow-tui-go` 启动时会优先复用 `/tmp` 下的缓存二进制，只有源码变化时才重新构建。
- 这样不会破坏已有使用习惯，同时可渐进切换到 Go 前端。

## 效果图导出（Snapshot）

为了方便编写文档或演示，Go TUI 支持“静态快照导出”模式。该模式不会启动交互式界面，而是直接渲染一帧画面并保存为 PNG 图片。

### 导出命令

使用 `tools/go_tui_snapshot.py` 脚本即可一键生成截图：

```bash
# 默认导出 raw 视图 (artifacts/screenshots/go_tui_snapshot_raw.png)
python3 tools/go_tui_snapshot.py --mode raw

# 导出 event 视图 (artifacts/screenshots/go_tui_snapshot_event.png)
python3 tools/go_tui_snapshot.py --mode event

# 导出失败场景的 timeline 视图
python3 tools/go_tui_snapshot.py --mode timeline --scenario failure

# 指定输出路径
python3 tools/go_tui_snapshot.py --mode raw --out /tmp/my_snapshot.png
```

### 依赖

该脚本依赖 `Pillow` (PIL) 库来渲染图片：

```bash
pip install Pillow
```

### 原理

1. 脚本会调用 `chipflow-tui-go` 并传入 `--snapshot-out` 等参数。
2. `chipflow-tui-go` 在内部模拟运行状态（支持 `success` / `failure` 两种场景），将 TUI 界面渲染为文本快照。
3. 脚本读取文本快照，使用等宽字体（优先尝试 `NotoSansMono` 或 `DejaVuSansMono`）将其渲染为 PNG 图片。
