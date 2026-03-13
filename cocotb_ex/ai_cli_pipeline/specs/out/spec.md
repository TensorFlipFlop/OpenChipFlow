# CDC Stream Packer Specification

## Overview

本文档定义 `cdc_stream_packer` 功能块的规范行为。该模块在 `clk1` 域按握手接收输入 beat，每连续 2 个被接受的 beat 组成 1 个完整输出 word，经内部异步 FIFO 传输到 `clk2` 域，并以 ready/valid 方式输出。

合规实现必须满足以下总体约束：

- 外部可观察行为必须与本文档一致。
- 命名状态与 `af_*` 接口信号必须在 DUT 作用域内保留，且在仿真中可通过层次路径访问。
- 允许采用等效微架构，但不得改变本文档定义的接口、握手语义、数据顺序、复位语义与可观测命名。

默认工作点如下：

- `clk1 = 100 MHz`
- `clk2 = 50 MHz`
- `IN_W = 1`
- `OUT_W = 2`
- `PACK_ORDER = 0`

逻辑功能可分解为以下三个部分：

- `clk1` 域 `Pack Buffer`：保存半包状态并生成完整 word
- 内部 `afifo`：执行 CDC 与跨域反压传播
- `clk2` 域 `Output Hold`：在下游反压期间保持输出稳定

## Supported Configurations

参数定义如下：

- `IN_W`：输入 beat 位宽，必须为正整数，默认值为 `1`
- `OUT_W`：输出 word 位宽，默认值为 `2`，且在所有合规配置中必须满足 `OUT_W = 2 * IN_W`
- `PACK_ORDER`：拼接顺序配置，`0 = {a, b}`，`1 = {b, a}`，默认值为 `0`

合法参数空间如下：

- `IN_W >= 1`
- `OUT_W == 2 * IN_W`
- `PACK_ORDER` 只能取 `0` 或 `1`

非法参数配置如下：

- `IN_W < 1`
- `OUT_W != 2 * IN_W`
- `PACK_ORDER` 不属于 `{0, 1}`

对非法参数配置，合规实现必须在 elaboration 期间拒绝构建，或在仿真/综合初始阶段报告 fatal 配置错误；不得以静默截断、隐式重映射或未定义输出代替。

每个合法参数组合都视为一个独立 elaboration。规范不要求运行时动态切换 `IN_W`、`OUT_W` 或 `PACK_ORDER`；对不同参数组合分别编译与运行属于合规使用方式。

## Interfaces

顶层端口定义如下：

```verilog
input  wire               clk1;
input  wire               clk1_rst_n;
input  wire [IN_W-1:0]    data_in;
input  wire               data_in_valid;
output wire               clk1_ready;

input  wire               clk2;
input  wire               clk2_rst_n;
output wire [OUT_W-1:0]   data_out;
output wire               data_out_valid;
input  wire               clk2_ready;
```

默认配置 `IN_W = 1`、`OUT_W = 2` 下：

- `data_in` 宽度为 `1` bit
- `data_out` 宽度为 `2` bit
- 顶层端口名必须精确为 `clk1`、`clk1_rst_n`、`data_in`、`data_in_valid`、`clk1_ready`、`clk2`、`clk2_rst_n`、`data_out`、`data_out_valid`、`clk2_ready`

内部 CDC 接口必须表现为一个语义符合本规范的 `afifo` 写侧/读侧 ready-valid 通道。以下信号名必须在 DUT 作用域内存在，且仿真时可通过层次路径直接访问：

- `af_wrclk`
- `af_wr_rst_n`
- `af_wr_data[OUT_W-1:0]`
- `af_wr_valid`
- `af_wr_ready`
- `af_rd_clk`
- `af_rd_rst_n`
- `af_rd_data[OUT_W-1:0]`
- `af_rd_valid`
- `af_rd_ready`

这些信号必须满足以下映射关系：

- `af_wrclk = clk1`
- `af_wr_rst_n = clk1_rst_n`
- `af_wr_data = packed_word[OUT_W-1:0]`
- `af_wr_valid` 表示写侧存在待写入完整 word
- `af_wr_ready` 表示 `afifo` 在该 `clk1` 周期可接受写入
- `af_rd_clk = clk2`
- `af_rd_rst_n = clk2_rst_n`
- `af_rd_data[OUT_W-1:0]` 表示 `afifo` 当前可供读取的完整 word
- `af_rd_valid` 表示 `afifo` 当前存在可读完整 word
- `af_rd_ready` 表示 `clk2` 侧可在该周期接收来自 `afifo` 的完整 word

`afifo` 必须满足以下语义：

- 在无复位打断的情况下，`wr_fire` 写入的完整 word 必须以相同顺序出现在 `af_rd_data`
- `afifo` 不得复制、丢弃或重排已经通过写侧握手提交的完整 word
- `afifo` 至少必须提供 `1` 个完整 word 的内部存储容量
- `afifo` 的精确深度只要求大于等于 `1`；更深容量允许存在，但不构成额外协议语义

## Reset and Initialization

复位信号定义如下：

- `clk1_rst_n`：`clk1` 域异步低有效复位
- `clk2_rst_n`：`clk2` 域异步低有效复位

复位断言可以发生在任意仿真时刻，包括两个有效时钟边沿之间。对异步复位控制的寄存器，复位值必须在复位下降沿后的同一仿真时间步内生效，仅允许存在零延迟调度造成的 delta-cycle 更新差异。

命名状态的强制复位值如下：

| State | Width | Reset Value |
| --- | --- | --- |
| `a_reg` | `IN_W` | `0` |
| `have_a` | `1` | `0` |
| `hold_word` | `OUT_W` | `0` |
| `hold_valid` | `1` | `0` |
| `out_data_reg` | `OUT_W` | `0` |
| `out_valid_reg` | `1` | `0` |

由上述状态导出的复位行为如下：

- 当 `clk1_rst_n = 0` 时，`Pack Buffer` 中未完成半包必须立即失效
- 当 `clk1_rst_n = 0` 时，尚未写入 `afifo` 的 `hold_word` 必须立即失效
- 当 `clk2_rst_n = 0` 时，`Output Hold` 中当前输出必须立即失效
- 当 `clk2_rst_n = 0` 时，`data_out_valid` 必须为 `0`
- 当 `clk2_rst_n = 0` 时，`data_out` 必须为 `0`

复位期间的事务语义如下：

- 当 `clk1_rst_n = 0` 时，不存在有效输入接受事件；该期间的 `data_in` 与 `data_in_valid` 不得形成被接受 beat
- 当 `clk1_rst_n = 0` 时，不存在有效 `afifo` 写入提交事件
- 当 `clk2_rst_n = 0` 时，不存在有效 `afifo` 读取装载事件
- 当 `clk2_rst_n = 0` 时，不存在有效输出传输事件

跨复位边界约束如下：

- `clk1` 复位前被接受的 beat 与 `clk1` 复位释放后被接受的 beat 不得组合成同一个输出 word
- `clk2` 复位释放后，`data_out_valid` 只能在装载新的完整 word 后重新置为 `1`

规范不要求 `clk1_rst_n` 与 `clk2_rst_n` 按固定顺序释放。复位释放后的定义行为从各自时钟域观察到第一个本地上升沿开始生效。

## Timing Model

事件定义如下：

- `in_fire`：某个 `clk1` 上升沿采样时满足 `clk1_rst_n = 1 && data_in_valid = 1 && clk1_ready = 1`
- `wr_fire`：某个 `clk1` 上升沿采样时满足 `clk1_rst_n = 1 && af_wr_valid = 1 && af_wr_ready = 1`
- `rd_fire`：某个 `clk2` 上升沿采样时满足 `clk2_rst_n = 1 && af_rd_valid = 1 && af_rd_ready = 1`
- `out_fire`：某个 `clk2` 上升沿采样时满足 `clk2_rst_n = 1 && data_out_valid = 1 && clk2_ready = 1`

平均吞吐约束如下：

```text
f_clk1 * IN_W <= f_clk2 * OUT_W
```

默认配置 `IN_W = 1`、`OUT_W = 2` 下，上式等价为：

```text
f_clk2 >= f_clk1 / 2
```

`clk1 = 100 MHz`、`clk2 = 50 MHz` 正好位于该边界条件。

跨时钟域绝对延迟不属于固定协议语义。以下两个量不要求对应固定整数拍数：

- `clk2_ready` 变化传播到 `clk1_ready` 的延迟
- 第 2 个 beat 被接受到相应 `data_out_valid` 首次出现的延迟

上述延迟允许随异步时钟相位关系、`afifo` 同步路径与当前 FIFO 占用状态变化。合规性依据是数据完整性、顺序一致性、稳态吞吐与反压正确性，而不是固定拍数。

在无积压优先级冲突的情况下，性能行为必须满足以下要求：

- 当第 2 个 beat 被接受并形成新的完整 word，且当前没有更早生成而尚未发送的 `hold_word` 占用写路径时，该完整 word 必须在同一个 `clk1` 周期驱动到 `af_wr_data`，并通过 `af_wr_valid` 对 `afifo` 可见
- 当当前输出 word 在某个 `clk2` 周期被消费且 `afifo` 在该周期同时提供下一完整 word 时，`clk2` 侧必须在同拍完成 refill，不得产生内部空泡

## Required Named State and Visibility

以下命名状态必须在 DUT 作用域内存在并可通过层次路径读取：

- `a_reg[IN_W-1:0]`
- `have_a`
- `hold_word[OUT_W-1:0]`
- `hold_valid`
- `out_data_reg[OUT_W-1:0]`
- `out_valid_reg`

以下命名组合信号也必须在 DUT 作用域内存在并可通过层次路径读取：

- `clk1_ready`
- `data_out[OUT_W-1:0]`
- `data_out_valid`
- `af_wrclk`
- `af_wr_rst_n`
- `af_wr_data[OUT_W-1:0]`
- `af_wr_valid`
- `af_wr_ready`
- `af_rd_clk`
- `af_rd_rst_n`
- `af_rd_data[OUT_W-1:0]`
- `af_rd_valid`
- `af_rd_ready`

允许存在额外状态、额外组合逻辑或额外流水，但不得删除、折叠、改名或隐藏上述命名状态与命名信号。

## Behavior

### Pack Buffer

输入 beat 仅在 `in_fire` 为真时被接受。任何不满足 `in_fire` 的 `data_in` 变化都不得影响后续输出序列。

当 `in_fire` 发生时：

- 若 `have_a = 0`，当前 beat 视为该输出 word 的第 1 个 beat `a`，必须写入 `a_reg`，并将 `have_a` 置为 `1`
- 若 `have_a = 1`，当前 beat 视为同一输出 word 的第 2 个 beat `b`，并与 `a_reg` 组成 `packed_word`

拼接规则如下：

- `PACK_ORDER = 0` 时，`packed_word = {a_reg, b}`
- `PACK_ORDER = 1` 时，`packed_word = {b, a_reg}`

其中：

- `packed_word` 高 `IN_W` 位表示输出 word 的高半部分
- `packed_word` 低 `IN_W` 位表示输出 word 的低半部分
- `OUT_W` 必须恒等于 `2 * IN_W`

当第 2 个 beat 形成完整 word 后：

- `have_a` 必须返回 `0`
- 该完整 word 必须转交到写侧发送路径或写侧 `hold_word`

奇数尾拍处理规则如下：

- 若输入序列以单个未配对的被接受 beat 结束，该 beat 必须保持在 `a_reg` 中，且 `have_a` 保持为 `1`
- 该未配对 beat 只能等待后续第 2 个 beat 或被 `clk1_rst_n = 0` 清除
- 模块不得自动补零、自动 flush、自动丢弃，或输出仅由单个 beat 组成的不完整 word

### Write-Side Flow Control

写侧必须满足以下组合关系：

- `gen_valid` 表示当前 `clk1` 周期由第 2 个被接受 beat 新生成了完整 word
- `af_wr_valid = hold_valid || gen_valid`
- `af_wr_data = hold_valid ? hold_word : gen_packed_word`

写侧发送优先级如下：

- 若 `hold_valid = 1`，`hold_word` 必须优先于同拍新生成完整 word 发送到 `afifo`
- 新生成完整 word 不得越过更早生成的 `hold_word`

状态更新规则如下：

- 若 `wr_fire = 1` 且本拍发送源为 `hold_word`，则 `hold_valid` 必须清零
- 若 `gen_valid = 1` 且该完整 word 未在当前拍通过 `wr_fire` 写入 `afifo`，则该完整 word 必须写入 `hold_word`，并将 `hold_valid` 置为 `1`
- `hold_word` 仅允许保存 `1` 个完整 word

`clk1_ready` 必须满足以下规则：

```text
clk1_ready = (have_a == 0) ? 1 : (hold_valid == 0)
```

该规则的强制含义如下：

- 当 `have_a = 0` 时，模块必须允许接受新的第 1 个 beat
- 当 `have_a = 1 && hold_valid = 0` 时，模块必须允许接受第 2 个 beat，因为当前至少存在 `hold_word` 这一落脚点
- 当 `have_a = 1 && hold_valid = 1` 时，模块必须禁止再接受会形成另一完整 word 的第 2 个 beat
- 模块不得通过接受额外 beat 后再丢弃的方式处理写侧存储压力

### Output Hold

输出映射必须满足：

- `data_out = out_data_reg`
- `data_out_valid = out_valid_reg`

读侧就绪条件必须满足：

```text
af_rd_ready = (!out_valid_reg) || (out_valid_reg && clk2_ready)
```

该规则的强制含义如下：

- 当当前输出为空时，`af_rd_ready` 必须为 `1`
- 当当前输出有效且下游在本拍接受该数据时，`af_rd_ready` 必须为 `1`
- 当 `data_out_valid = 1 && clk2_ready = 0` 时，`af_rd_ready` 必须为 `0`

读侧装载规则如下：

- 若 `rd_fire = 1`，则 `af_rd_data` 必须装载到 `out_data_reg`，并将 `out_valid_reg` 置为 `1`
- 若当前输出在本拍被消费且未发生 `rd_fire`，则 `out_valid_reg` 必须清为 `0`
- 若当前输出在本拍被消费且同时发生 `rd_fire`，则新 word 必须在同拍装载到 `out_data_reg`，`out_valid_reg` 必须保持为 `1`

阻塞保持规则如下：

- 当 `data_out_valid = 1 && clk2_ready = 0` 时，`data_out` 必须保持稳定
- 当 `data_out_valid = 1 && clk2_ready = 0` 时，`data_out_valid` 必须保持稳定
- 上述稳定性必须持续到发生 `out_fire` 或 `clk2_rst_n = 0`

### Data Integrity and Backpressure

完整性与顺序要求如下：

- 仅满足 `in_fire` 的 beat 才计入输入序列
- 每连续 `2` 个被接受 beat 必须对应且仅对应 `1` 个输出 word
- 输出 word 的顺序必须与输入 beat 的接受顺序一致
- 模块不得重复输出、跳过输出或重排输出 word

反压要求如下：

- 当 `clk2_ready` 间歇或持续为 `0` 导致输出侧停滞时，模块必须通过 `clk1_ready` 向上游施加反压
- 反压传播的绝对拍数不固定，但模块必须在任何被接受数据会被覆盖之前完成限流
- 若 `clk2_ready` 后续重新返回 `1` 且期间无进一步复位，则所有已被接受且已组成完整 word 的数据必须最终按序排空

第 1 个 beat 在反压期间的保持要求如下：

- 当某个输出 word 的第 1 个 beat 已被接受而第 2 个 beat 尚未被接受时，该第 1 个 beat 必须在 `a_reg` 中持续保留
- 该保持必须持续到匹配的第 2 个 beat 被接受，或 `clk1_rst_n = 0`

缓存能力的最低要求如下：

- `Pack Buffer` 必须提供 `1` 个 beat 的半包保持能力，即 `a_reg`
- 写侧必须提供 `1` 个完整 word 的暂存能力，即 `hold_word`
- `Output Hold` 必须提供 `1` 个完整 word 的输出保持能力，即 `out_data_reg`
- `afifo` 必须提供至少 `1` 个完整 word 的内部存储能力

`afifo` 的精确深度、达到反压之前还能继续接受的额外 beat 数、以及首个输出 word 的绝对出现周期都不是固定协议参数；这些量可随实现与异步时钟相位关系变化。合规性只要求不丢失已接受数据、最终正确反压、最终正确排空，以及在稳态条件下满足吞吐要求。

默认工作点下的边界吞吐要求如下：

- 条件：`IN_W = 1`、`OUT_W = 2`、`clk1 = 100 MHz`、`clk2 = 50 MHz`、`clk2_ready` 持续为 `1`
- 在上述条件下，模块必须支持输入端按 `clk1` 每拍接受 `1` 个 beat 的持续传输
- 在首个输出 word 变为有效之后，输出端必须按 `clk2` 每拍提供 `1` 个有效 word
- 在上述稳态阶段，模块不得引入内部气泡，不得丢失数据，不得重排数据

## Error Handling

本模块不定义独立错误上报端口。异常规避必须依赖参数合法性检查、ready-valid 握手与反压机制完成。

合规实现必须满足以下错误处理约束：

- 不得以丢弃已接受 beat 的方式避免溢出
- 不得在 `af_rd_valid = 0` 时伪造有效输出 word
- 不得在非法参数配置下继续以表面可运行但语义不确定的方式工作

## Glossary

| Term | Definition |
| --- | --- |
| `beat` | `clk1` 域一次被接受的输入传输，位宽为 `IN_W` |
| `word` | 由连续 `2` 个被接受输入 beat 组成的输出数据单元，位宽为 `OUT_W = 2 * IN_W` |
| `a` | 某个输出 word 的第 `1` 个被接受 beat |
| `b` | 同一输出 word 的第 `2` 个被接受 beat |
| `Pack Buffer` | `clk1` 域内负责半包缓存与完整 word 生成的逻辑 |
| `afifo` | 用于 CDC 与跨域反压传播的内部异步 FIFO 抽象接口 |
| `Output Hold` | `clk2` 域内在下游反压期间保持输出稳定的寄存器逻辑 |
| `in_fire` | `clk1` 上升沿采样到 `clk1_rst_n && data_in_valid && clk1_ready` 为真，表示输入 beat 被接受 |
| `wr_fire` | `clk1` 上升沿采样到 `clk1_rst_n && af_wr_valid && af_wr_ready` 为真，表示完整 word 写入 `afifo` |
| `rd_fire` | `clk2` 上升沿采样到 `clk2_rst_n && af_rd_valid && af_rd_ready` 为真，表示 `afifo` 数据装载到 `Output Hold` |
| `out_fire` | `clk2` 上升沿采样到 `clk2_rst_n && data_out_valid && clk2_ready` 为真，表示输出 word 被下游消费 |
