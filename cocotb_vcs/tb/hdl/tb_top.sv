`timescale 1ns/1ps
`default_nettype none

module tb_top #(parameter int W = 8) ();
    logic           clk;
    logic           rst_n;
    logic           in_valid;
    logic           in_ready;
    logic [W-1:0]   a;
    logic [W-1:0]   b;
    logic           out_valid;
    logic           out_ready;
    logic [W:0]     sum;

    adder #(.W(W)) dut (
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(in_valid),
        .in_ready(in_ready),
        .a(a),
        .b(b),
        .out_valid(out_valid),
        .out_ready(out_ready),
        .sum(sum)
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
                $fsdbDumpvars(0, tb_top.dut);
            end else begin
                $fsdbDumpvars(0, tb_top);
            end
            $fsdbDumpMDA();
`else
            $display("[tb_top] FSDB plusarg set but FSDB macro not enabled.");
`endif
        end
        if ($test$plusargs("VCD")) begin
            $dumpfile("waves.vcd");
            // 默认全量 dump；加 +DUT_ONLY 仅 dump dut
            if ($test$plusargs("DUT_ONLY")) begin
                $dumpvars(0, tb_top.dut);
            end else begin
                $dumpvars(0, tb_top);
            end
        end
    end
endmodule

`default_nettype wire
