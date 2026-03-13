## 0. 模块命名

推荐模块名：**`cdc_stream_packer`**
含义：跨时钟域（CDC）的流式打包器（把 clk1 的 2 个 beat 打包成 clk2 的 1 个 word）。

---

## 1. 顶层端口（固定按你给的）

```verilog
// clk1域接口
input  wire       clk1,          // 100MHz
input  wire       clk1_rst_n,    // clk1域异步复位，低有效
input  wire       data_in,       // clk1域的输入数据（每周期1位）
input  wire       data_in_valid, // clk1域的输入数据有效信号
output reg        clk1_ready,    // clk1域的发送就绪信号

// clk2域接口
input  wire       clk2,          // 50MHz
input  wire       clk2_rst_n,    // clk2域异步复位，低有效
output reg  [1:0] data_out,      // clk2域的输出数据（每周期2位）
output reg        data_out_valid,// clk2域的输出数据有效信号
input  wire       clk2_ready     // clk2域的接收就绪信号
```

---

## 2. 参数（拼接顺序可配；位宽可配作为扩展点）

* `PACK_ORDER`（必须）：0 = `{a,b}`，1 = `{b,a}`
* `IN_W/OUT_W`（必须）：本端口默认配置为 `IN_W=1, OUT_W=2`。位宽可配置，端口 `[IN_W-1:0] data_in` / `[2*IN_W-1:0] data_out`

---

## 3. 强制 afifo 接口
* 注意1：afifo必须用af_*开头的信号，那么就决定了afifo输入输出接口是带握手的，进而决定了afifo的握手逻辑需要在afifo内部实现！！！！
* 注意2：afifo是可能用到的内部模块。需要根据接口定义反推afifo功能，并编写一个afifo子模块在顶层模块中调用。  
> afifo 名称可加前缀，避免与顶层同名。下面用 `af_` 前缀示意（接口语义不变）。

**写侧（clk1 域）**

* `af_wrclk   = clk1`
* `af_wr_rst_n= clk1_rst_n`
* `af_wr_data = packed_word[1:0]`
* `af_wr_valid`
* `af_wr_ready`

**读侧（clk2 域）**

* `af_rd_clk  = clk2`
* `af_rd_rst_n= clk2_rst_n`
* `af_rd_ready`
* `af_rd_valid`
* `af_rd_data = af_rd_data[1:0]`

---

## 4. 推荐微架构（pack buffer + afifo + output hold）

### 4.1 总体框图

```text
clk1 domain                                    clk2 domain
┌──────────────────────┐                      ┌────────────────────────┐
│ input handshake      │                      │ output handshake       │
│ data_in/valid/ready  │                      │ data_out/valid/ready   │
└─────────┬────────────┘                      └─────────┬──────────────┘
          │                                             │
          ▼                                             ▼
┌──────────────────────┐   wr_*     rd_*      ┌──────────────────────┐
│ Pack Buffer          │ ───────────────►     │ Output Hold Register │
│ - a_reg (1bit)       │   Async FIFO         │ - out_data_reg (2b)  │
│ - have_a (1bit)      │ ◄──────────────      │ - out_valid_reg      │
│ - hold_word (2bit)   │                      └──────────────────────┘
│ - hold_valid (1bit)  │
└──────────────────────┘
```

> 说明：
>
> * **Pack Buffer**：负责把两次输入 beat 凑成一个 2bit word；
> * **afifo**：CDC 与跨域反压核心；
> * **Output Hold**：保证 `data_out_valid=1 && clk2_ready=0` 时输出稳定。

---

## 5. clk1 域 Pack Buffer：寄存器、规则与 ready 计算

### 5.1 需要的 clk1 域寄存器（每个都是独立 always 的候选）

* `a_reg`：保存第 1 个 beat（a）
* `have_a`：是否已经收到了 a（0/1）
* `hold_word[1:0]`：完整打包 word 的暂存（当 FIFO 暂时不 ready 时）
* `hold_valid`：`hold_word` 是否有效

### 5.2 输入握手与组包规则（功能逻辑）

* 输入 beat **被接受**条件：`in_fire = data_in_valid && clk1_ready`
* 当 `in_fire`：

  * 若 `have_a==0`：`a_reg <= data_in`，`have_a<=1`
  * 若 `have_a==1`：此 beat 视为 `b=data_in`，形成 `packed_word`：

    * `PACK_ORDER=0`：`packed = {a_reg, b}`
    * `PACK_ORDER=1`：`packed = {b, a_reg}`
    * 之后 `have_a<=0`（回到等待 a 的状态）
    * 若 FIFO 此时可写（`af_wr_ready==1` 且你允许“当拍直写”）：可以直接发起写入（见 5.3）；否则写到 `hold_word/hold_valid`。

### 5.3 写入 afifo 的策略（保证吞吐 + 最小延迟）

**目标：**第二个 beat 到来时，若可能，尽量**不多等 1 个 clk1 周期**。

推荐做法（概念）：

* 产生一个“写源”：

  * `gen_valid`：本拍由 a_reg+b 生成的 packed_word（当 `in_fire && have_a==1`）
  * `hold_valid`：历史生成但未写入的 hold_word
* 写端口选择优先级：`hold_valid` 优先（先清积压），否则用 `gen_valid`

写端握手定义：

* `af_wr_valid = hold_valid || gen_valid`
* `af_wr_data  = hold_valid ? hold_word : gen_packed_word`
* `wr_fire = af_wr_valid && af_wr_ready`（在 clk1 上升沿生效）

寄存器更新原则：

* 如果 `wr_fire` 且当前用的是 `hold_valid`：清 `hold_valid`
* 如果 `gen_valid` 发生但本拍没写进去（`af_wr_ready==0` 或被 hold 抢占）：把 `gen_packed_word` 存入 `hold_word` 并置 `hold_valid=1`

> 关键点：**hold_word 只需要 1 深度**就够，因为每形成一个 word 都依赖“第二个 beat”，我们通过 `clk1_ready` 保证不会在 `hold_valid=1` 时再形成第二个完整 word。

### 5.4 clk1_ready 的推荐计算（核心，防溢出 + 允许半包停住）

最简单且安全（推荐）：

* 当 `have_a==0`：可以接受第一个 beat（只占用 a_reg），**不依赖 FIFO**
* 当 `have_a==1`：下一拍接受就会形成完整 word，因此要求 **至少有一个 word 的落脚点**（hold_word 空）

所以：

```text
clk1_ready = (have_a == 0) ? 1 : (hold_valid == 0);
```

解释：

* `hold_valid==1` 表示已经有一个完整 word 堵在 packer 侧，不能再接收第二个 beat（否则会产生第二个完整 word 无处可放）。
* 允许在 `hold_valid==1` 时仍接收“第一个 beat”（have_a==0），这能减少提前反压，但会导致该 beat 可能等待更久才配对——这是 backpressure 下的必然代价，且不丢数据。

> 如果你希望“内部不允许额外缓存半包（a_reg）”以减少不确定延迟，也可以更激进地：`clk1_ready = !hold_valid && (!have_a || af_wr_ready || ... )`，但通常没必要，反而降低吞吐。

---

## 6. clk2 域 Output Hold：与 afifo 的 rd_* 对接（支持反压 + 无气泡）

### 6.1 clk2 域寄存器

* `out_data_reg[1:0]`
* `out_valid_reg`

输出映射：

* `data_out       = out_data_reg`
* `data_out_valid = out_valid_reg`

### 6.2 out_hold 的工作规则

* 当 `out_valid_reg==1 && clk2_ready==1`：当前输出 word 被消费
* 当 `out_valid_reg==0`：可以从 afifo 取新 word
* 为了无气泡：当“本拍会消费旧 word”同时 afifo 也有新 word，可同拍 refill（保持 out_valid=1）

### 6.3 afifo 读侧 ready 的计算（rd_ready）

`af_rd_ready` 表示 **output hold 是否能接收** afifo 给的数据：

```text
af_rd_ready = (!out_valid_reg) || (out_valid_reg && clk2_ready);
```

含义：

* out 为空：当然能接；
* out 满但下游 ready=1：本拍会消费旧的，因此也能接新数据 refill。

### 6.4 从 afifo 装载输出（握手）

* `rd_fire = af_rd_valid && af_rd_ready`（在 clk2 上升沿生效）

更新：

* 若 `rd_fire`：`out_data_reg <= af_rd_data`，`out_valid_reg <= 1`
* 否则若 `out_valid_reg && clk2_ready` 且没有 rd_fire（说明 fifo 空）：`out_valid_reg <= 0`

> 这样可以严格保证：
>
> * `data_out_valid=1 && clk2_ready=0` 时 `data_out` 恒定；
> * 下游 ready 连续为 1 且 fifo 连续有数时可做到 **每拍一个 word**，无气泡。

---

## 7. 频率/吞吐限制（必须写进方案的“系统约束”）

本设计把 **2 个 clk1 beat** 打成 **1 个 clk2 word**（2bit）。理论上若 `clk2_ready` 长期为 1，持续不丢数需要满足：

* 平均输入 bit-rate ≤ 平均输出 bit-rate
  即：`f_clk1 * 1 <= f_clk2 * 2` → `f_clk2 >= f_clk1/2`

你给的 100MHz / 50MHz 刚好边界满足；若 `clk2_ready` 不是一直为 1，则等效输出速率下降，模块将通过 `clk1_ready` 反压来避免 overflow。

---

## 8. 延迟最小化策略（在你约束下能做到的“最小”）

* 不可避免的“组包延迟”：必须等到收齐 a,b 才能输出 2bit word。
* CDC 的不可避免延迟：afifo 指针同步通常会引入若干周期延迟（实现决定）。
* 方案层面可优化点：

  1. **第二个 beat 到来时尽量当拍发起 afifo 写（gen_valid）**，避免额外一拍；
  2. clk2 侧采用上述 **refill 逻辑**，保证无气泡输出。

---

## 9. 验证点更新（针对 afifo 接口与反压）

### 9.1 必测断言/检查

1. **输入采样只在握手**：scoreboard 只在 `data_in_valid && clk1_ready` 记录 beat。
2. **输出比较只在握手**：只在 `data_out_valid && clk2_ready` 弹出期望 word 并比对。
3. **输出保持**：当 `data_out_valid==1 && clk2_ready==0`，`data_out` 必须保持不变（你要求反压）。
4. **半包停住**：`have_a==1` 后若发生长反压，应能停住不丢，恢复后继续正确组包。
5. **PACK_ORDER 覆盖**：两种拼接配置均通过。
6. **队列不空/不溢**（scoreboard层面）：DUT 输出次数不得超过期望次数；最终 drain 后期望队列应为空。

### 9.2 覆盖建议

* clk2_ready：随机抖动 + 长时间 0
* data_in_valid：随机 + 连续 1（满速输入）
* 边界：反压发生在 `have_a==1`（已收 a 等 b）这一时刻
* 极限：100MHz/50MHz 下满速输入，clk2_ready 置 1（应做到持续无丢、无气泡输出）
