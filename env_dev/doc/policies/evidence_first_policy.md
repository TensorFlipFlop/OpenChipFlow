# Evidence First Policy (质量门禁 - 证据优先原则)

> **核心原则**：所有放行决策（Pass/Fail）必须基于机器可读的结构化证据（Artifacts），严禁仅凭 LLM 的自然语言回复（"I checked it, it works"）作为放行依据。

## 1. 适用范围
本策略适用于 OpenChipFlow 中所有涉及代码生成、验证、综合及发布的自动化流程节点（Gates）。

## 2. 证据定义
有效的“证据”必须满足以下条件：
1. **持久化**：必须以文件形式存在于 `artifacts/runs/<run_id>/` 目录下。
2. **结构化**：格式必须为 JSON, XML, YAML, CSV 或特定领域的标准报告格式（如 Coverage DB, Waveform）。
3. **可验证**：具备 Schema 或校验脚本，可自动判断其合法性。

## 3. 实施规则 (Rules)

### Rule 1: No Evidence, No Pass
任何 Gate 节点在输出 "PASS" 之前，必须先验证对应的 Evidence 文件是否存在且非空。
*   ❌ 错误：LLM 回复 "代码已生成"，直接进入下一阶段。
*   ✅ 正确：检查 `generated_code.v` 存在，且 `syntax_check.log` 显示 `Errors: 0`，才允许进入下一阶段。

### Rule 2: Machine-Readable over Human-Readable
优先使用机器解析结果。
*   ❌ 错误：解析 LLM 的对话文本寻找 "Success" 关键词。
*   ✅ 正确：解析工具输出的 `exit_code` 或 JSON 报告中的 `status` 字段。

### Rule 3: Traceability (溯源)
每个放行决策必须链接到具体的证据文件路径。
*   Log 示例：`Gate passed. Evidence: artifacts/runs/run_123/verification/results.json`

## 4. 违规处理
违反本策略的 PR 或流程变更将被拒绝合入。
发现无证据放行的 Run 将被标记为 "Unreliable" 并触发告警。
