`timescale 1ns/1ps
`ifndef CONTROL_VARIANT
`define CONTROL_VARIANT 15
`endif
module readers_control_tb;
    logic clk = 0;
    always #2 clk = !clk;
    logic rst_n = 0;
    logic [63:0] awaddr = 0, araddr = 0, wdata = 0, rdata;
    logic [7:0] wstrb = 0;
    logic awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    wire awready, wready, bvalid, arready, rvalid;
    wire [1:0] bresp, rresp;
    logic [23:0] events = 0;
    logic [63:0] counters [16];
    logic engine_ready = 1, engine_done = 0, engine_error = 0, result_valid = 0;
    logic [31:0] result_bits = 32'h3f800000;
    wire start, busy;
    wire [63:0] config_words [16];
    wire [63:0] tick, active_setting;
    logic [63:0] value;
    int accepted = 0;
    reader_control #(.VARIANT(`CONTROL_VARIANT)) control(.*);
    always @(posedge clk) if (start) accepted++;

    task automatic write_register(input int index, input logic [63:0] data);
        @(negedge clk);
        awaddr = 64'(index * 8);
        awvalid = 1;
        @(negedge clk);
        awvalid = 0;
        repeat (2) @(negedge clk);
        wdata = data;
        wstrb = '1;
        wvalid = 1;
        @(negedge clk);
        wvalid = 0;
        repeat (3) @(negedge clk);
    endtask

    task automatic read_register(input int index, output logic [63:0] data);
        @(negedge clk);
        araddr = 64'(index * 8);
        arvalid = 1;
        @(negedge clk);
        arvalid = 0;
        if (!rvalid) $fatal(1, "Missing CSR response");
        data = rdata;
        @(negedge clk);
    endtask

    task automatic frame(input int selected, input int effective);
        engine_done = 0;
        write_register(14, 64'(selected));
        write_register(0, 1);
        if (!busy || active_setting != effective) $fatal(1, "Setting not latched at arm");
        write_register(14, 999);
        if (config_words[14] != selected || active_setting != effective)
            $fatal(1, "Live setting changed");
        @(negedge clk);
        events = 24'h000003;
        result_valid = 1;
        @(negedge clk);
        events = 0;
        result_valid = 0;
        repeat (3) @(negedge clk);
        if (!busy) $fatal(1, "Result ended frame before full drain");
        engine_done = 1;
        repeat (3) @(negedge clk);
        read_register(0, value);
        if (value != 10) $fatal(1, "Drained frame did not succeed");
        read_register(41, value);
        if (value != effective) $fatal(1, "Active-setting readback mismatch");
    endtask

    initial begin
        int previous;
        for (int i = 0; i < 16; i++) counters[i] = 64'(i);
        repeat (3) @(negedge clk);
        rst_n = 1;
        read_register(4, value);
        if (value != (64'h4342595400060000 | 64'(`CONTROL_VARIANT))) $fatal(1, "ABI6 mismatch");
        write_register(1, 4097);
        write_register(8, 64'h200000);
        if (`CONTROL_VARIANT == 14) frame(0, 0);
        if (`CONTROL_VARIANT == 15) begin
            frame(0, 4);
            frame(1, 1);
            frame(2, 2);
            frame(4, 4);
            frame(8, 8);
        end
        if (`CONTROL_VARIANT == 16) begin
            frame(0, 32);
            frame(32, 32);
            frame(64, 64);
            frame(128, 128);
        end
        engine_done = 0;
        previous = accepted;
        write_register(14, 3);
        write_register(0, 1);
        if (busy || accepted != previous) $fatal(1, "Invalid setting started DMA");
        read_register(0, value);
        if (!value[2]) $fatal(1, "Invalid setting was not rejected");
        @(negedge clk);
        rst_n = 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        read_register(0, value);
        if (value != 0) $fatal(1, "Reset did not clear the control state");
        $display("PASS ABI6 variant=%0d runtime settings, immutable frames, invalid-before-DMA, drain and reset", `CONTROL_VARIANT);
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "Control watchdog");
    end
endmodule
