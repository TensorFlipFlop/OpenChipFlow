`timescale 1ns/1ps
`default_nettype none

module sync_fifo #(
    parameter int W = 8,
    parameter int DEPTH = 16
) (
    input  logic         clk,
    input  logic         rst_n,

    // write side
    input  logic         wr_valid,
    output logic         wr_ready,
    input  logic [W-1:0] wr_data,

    // read side (show-ahead / fall-through)
    output logic         rd_valid,
    input  logic         rd_ready,
    output logic [W-1:0] rd_data,

    // status
    output logic         full,
    output logic         empty
);

    localparam int ADDR_W = (DEPTH <= 2) ? 1 : $clog2(DEPTH);

    localparam logic [ADDR_W-1:0] LAST_PTR = ADDR_W'(DEPTH - 1);
    localparam logic [ADDR_W:0]   DEPTH_CNT = (ADDR_W + 1)'(DEPTH);

    logic [W-1:0] mem [0:DEPTH-1];
    logic [ADDR_W-1:0] wptr;
    logic [ADDR_W-1:0] rptr;
    logic [ADDR_W:0]   count;

    assign full  = (count == DEPTH_CNT);
    assign empty = (count == 0);

    assign wr_ready = !full;
    assign rd_valid = !empty;

    // Show-ahead read datapath: stable while rptr doesn't move.
    assign rd_data = mem[rptr];

    logic push;
    logic pop;
    assign push = wr_valid && wr_ready;
    assign pop  = rd_valid && rd_ready;

`ifndef SYNTHESIS
    logic [W-1:0] rd_data_prev;
    logic         rd_hold_prev;
`endif

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wptr  <= '0;
            rptr  <= '0;
            count <= '0;
`ifndef SYNTHESIS
            rd_data_prev <= '0;
            rd_hold_prev <= 1'b0;
`endif
        end else begin
`ifndef SYNTHESIS
            if (rd_hold_prev && rd_valid && !rd_ready) begin
                assert (rd_data == rd_data_prev)
                  else $fatal(1, "fifo rd_data changed while holding rd_valid && !rd_ready");
            end
            rd_data_prev <= rd_data;
            rd_hold_prev <= (rd_valid && !rd_ready);
`endif

            unique case ({push, pop})
                2'b10: begin
                    mem[wptr] <= wr_data;
                    wptr      <= (wptr == LAST_PTR) ? '0 : (wptr + 1'b1);
                    count     <= count + 1'b1;
                end
                2'b01: begin
                    rptr  <= (rptr == LAST_PTR) ? '0 : (rptr + 1'b1);
                    count <= count - 1'b1;
                end
                2'b11: begin
                    mem[wptr] <= wr_data;
                    wptr      <= (wptr == LAST_PTR) ? '0 : (wptr + 1'b1);
                    rptr      <= (rptr == LAST_PTR) ? '0 : (rptr + 1'b1);
                end
                default: begin
                end
            endcase
        end
    end
endmodule

`default_nettype wire
