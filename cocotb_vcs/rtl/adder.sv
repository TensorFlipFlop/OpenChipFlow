`timescale 1ns/1ps
`default_nettype none

module adder #(parameter int W = 8) (
    input  logic           clk,
    input  logic           rst_n,        // 低有效复位
    // 输入握手
    input  logic           in_valid,
    output logic           in_ready,
    input  logic [W-1:0]   a,
    input  logic [W-1:0]   b,
    // 输出握手
    output logic           out_valid,
    input  logic           out_ready,
    output logic [W:0]     sum           // W+1位，含进位
);

    // 单元素缓冲背压：当 out_valid=1 且 out_ready=0 时，in_ready=0
    assign in_ready = ~out_valid | (out_valid & out_ready);

    logic [W:0] sum_r;
    assign sum = sum_r;

`ifndef SYNTHESIS
    logic [W:0] sum_r_prev;
    logic       hold_prev;
`endif

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            sum_r     <= '0;
`ifndef SYNTHESIS
            sum_r_prev <= '0;
            hold_prev  <= 1'b0;
`endif
        end else begin
`ifndef SYNTHESIS
            // —— 即时断言（VCS/Verilator 友好）——
            // 背压持续期间（连续多个周期 out_valid && !out_ready），输出数据必须保持不变。
            // 注：不能直接用 $stable(sum_r) 并仅在背压条件下调用，否则会跨“非背压区间”比较，产生误报。
            if (hold_prev && out_valid && !out_ready) begin
                assert (sum_r == sum_r_prev)
                  else $fatal(1, "sum changed under backpressure");
            end
            sum_r_prev <= sum_r;
            hold_prev  <= (out_valid && !out_ready);
`endif

            // 主逻辑：就绪即接收；结果寄存；拉高 out_valid；出站被消费即清零
            if (in_valid && in_ready) begin
                sum_r     <= a + b;
                out_valid <= 1'b1;
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end
    end
endmodule

`default_nettype wire
