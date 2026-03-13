`timescale 1ns/1ps

module ai_dut #(
    parameter int IN_W       = 1,
    parameter int OUT_W      = 2 * IN_W,
    parameter int PACK_ORDER = 0
) (
    input  logic             clk1,
    input  logic             clk1_rst_n,
    input  logic [IN_W-1:0]  data_in,
    input  logic             data_in_valid,
    output logic             clk1_ready,

    input  logic             clk2,
    input  logic             clk2_rst_n,
    output logic [OUT_W-1:0] data_out,
    output logic             data_out_valid,
    input  logic             clk2_ready,

    output logic             af_wrclk,
    output logic             af_wr_rst_n,
    output logic [OUT_W-1:0] af_wr_data,
    output logic             af_wr_valid,
    input  logic             af_wr_ready,

    output logic             af_rd_clk,
    output logic             af_rd_rst_n,
    input  logic [OUT_W-1:0] af_rd_data,
    input  logic             af_rd_valid,
    output logic             af_rd_ready
);

    // clk1 domain state
    logic [IN_W-1:0]  a_reg;
    logic             have_a;
    logic [OUT_W-1:0] hold_word;
    logic             hold_valid;

    // clk2 domain state
    logic [OUT_W-1:0] out_data_reg;
    logic             out_valid_reg;

    // clk1 domain next-state
    logic [IN_W-1:0]  next_a_reg;
    logic             next_have_a;
    logic [OUT_W-1:0] next_hold_word;
    logic             next_hold_valid;

    // clk2 domain next-state
    logic [OUT_W-1:0] next_out_data_reg;
    logic             next_out_valid_reg;

    // Centralized handshake conditions
    logic [OUT_W-1:0] gen_packed_word;
    logic             in_fire;
    logic             first_beat_fire;
    logic             second_beat_fire;
    logic             gen_valid;
    logic             wr_fire;
    logic             rd_fire;
    logic             out_fire;

    assign af_wrclk    = clk1;
    assign af_wr_rst_n = clk1_rst_n;
    assign af_rd_clk   = clk2;
    assign af_rd_rst_n = clk2_rst_n;

    assign clk1_ready = !have_a || !hold_valid;
    assign in_fire    = data_in_valid && clk1_ready;
    assign first_beat_fire  = in_fire && !have_a;
    assign second_beat_fire = in_fire && have_a;

    assign gen_packed_word = (PACK_ORDER == 0) ? {a_reg, data_in} : {data_in, a_reg};
    assign gen_valid       = second_beat_fire;

    assign af_wr_valid = hold_valid || gen_valid;
    assign af_wr_data  = hold_valid ? hold_word : gen_packed_word;
    assign wr_fire     = af_wr_valid && af_wr_ready;

    assign af_rd_ready = !out_valid_reg || (out_valid_reg && clk2_ready);
    assign rd_fire     = af_rd_valid && af_rd_ready;
    assign out_fire    = out_valid_reg && clk2_ready;

    assign data_out       = out_data_reg;
    assign data_out_valid = out_valid_reg;

    always_comb begin
        next_a_reg         = a_reg;
        next_have_a        = have_a;
        next_hold_word     = hold_word;
        next_hold_valid    = hold_valid;
        next_out_data_reg  = out_data_reg;
        next_out_valid_reg = out_valid_reg;

        if (first_beat_fire) begin
            next_a_reg  = data_in;
            next_have_a = 1'b1;
        end

        if (second_beat_fire) begin
            next_have_a = 1'b0;
        end

        if (hold_valid && wr_fire) begin
            next_hold_valid = 1'b0;
        end

        if (gen_valid && !wr_fire) begin
            next_hold_word  = gen_packed_word;
            next_hold_valid = 1'b1;
        end

        if (rd_fire) begin
            next_out_data_reg  = af_rd_data;
            next_out_valid_reg = 1'b1;
        end else if (out_fire) begin
            next_out_valid_reg = 1'b0;
        end
    end

    always_ff @(posedge clk1 or negedge clk1_rst_n) begin
        if (!clk1_rst_n) begin
            a_reg      <= '0;
            have_a     <= 1'b0;
            hold_word  <= '0;
            hold_valid <= 1'b0;
        end else begin
            a_reg      <= next_a_reg;
            have_a     <= next_have_a;
            hold_word  <= next_hold_word;
            hold_valid <= next_hold_valid;
        end
    end

    always_ff @(posedge clk2 or negedge clk2_rst_n) begin
        if (!clk2_rst_n) begin
            out_data_reg  <= '0;
            out_valid_reg <= 1'b0;
        end else begin
            out_data_reg  <= next_out_data_reg;
            out_valid_reg <= next_out_valid_reg;
        end
    end

endmodule
