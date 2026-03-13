`timescale 1ns/1ps

module ai_tb_top #(
    parameter int IN_W = 1,
    parameter int OUT_W = 2,
    parameter int PACK_ORDER = 0
) (
    input  logic             clk1,
    input  logic             clk1_rst_n,
    input  logic [IN_W-1:0]  data_in,
    input  logic             data_in_valid,
    output wire              clk1_ready,
    input  logic             clk2,
    input  logic             clk2_rst_n,
    output wire [OUT_W-1:0]  data_out,
    output wire              data_out_valid,
    input  logic             clk2_ready
);

    ai_dut #(
        .IN_W(IN_W),
        .OUT_W(OUT_W),
        .PACK_ORDER(PACK_ORDER)
    ) dut (
        .clk1(clk1),
        .clk1_rst_n(clk1_rst_n),
        .data_in(data_in),
        .data_in_valid(data_in_valid),
        .clk1_ready(clk1_ready),
        .clk2(clk2),
        .clk2_rst_n(clk2_rst_n),
        .data_out(data_out),
        .data_out_valid(data_out_valid),
        .clk2_ready(clk2_ready)
    );

endmodule
