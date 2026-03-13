`timescale 1ns/1ps
`default_nettype none

module tb_fifo #(
    parameter int W = 8,
    parameter int DEPTH = 16
) ();
    logic         clk;
    logic         rst_n;

    logic         wr_valid;
    logic         wr_ready;
    logic [W-1:0] wr_data;

    logic         rd_valid;
    logic         rd_ready;
    logic [W-1:0] rd_data;

    logic         full;
    logic         empty;

    sync_fifo #(.W(W), .DEPTH(DEPTH)) dut (
        .clk(clk),
        .rst_n(rst_n),
        .wr_valid(wr_valid),
        .wr_ready(wr_ready),
        .wr_data(wr_data),
        .rd_valid(rd_valid),
        .rd_ready(rd_ready),
        .rd_data(rd_data),
        .full(full),
        .empty(empty)
    );

    // 波形导出：默认 FSDB（需 Verdi PLI），否则可切 VCD
    initial begin
        if ($test$plusargs("FSDB")) begin
`ifdef FSDB
            string fsdb_name;
            if (!$value$plusargs("fsdbfile=%s", fsdb_name)) fsdb_name = "waves.fsdb";
            $fsdbDumpfile(fsdb_name);
            // 默认全量 dump；加 +DUT_ONLY 仅 dump dut 以减小波形
            if ($test$plusargs("DUT_ONLY")) begin
                $fsdbDumpvars(0, tb_fifo.dut);
            end else begin
                $fsdbDumpvars(0, tb_fifo);
            end
            $fsdbDumpMDA();
`else
            $display("[tb_fifo] FSDB plusarg set but FSDB macro not enabled.");
`endif
        end
        if ($test$plusargs("VCD")) begin
            $dumpfile("waves.vcd");
            // 默认全量 dump；加 +DUT_ONLY 仅 dump dut
            if ($test$plusargs("DUT_ONLY")) begin
                $dumpvars(0, tb_fifo.dut);
            end else begin
                $dumpvars(0, tb_fifo);
            end
        end
    end
endmodule

`default_nettype wire
