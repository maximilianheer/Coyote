`timescale 1ns/1ps
module deployment_control_tb;
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
    logic [31:0] result_bits = 32'hbf800000;
    wire start, busy;
    wire [63:0] config_words [16];
    wire [63:0] tick;
    logic [63:0] value;
    deployment_control control(.*);

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

    initial begin
        for (int i = 0; i < 16; i++) counters[i] = 64'(i);
        repeat (3) @(negedge clk);
        rst_n = 1;
        read_register(4, value);
        if (value != 64'h434259540005000a) $fatal(1, "ABI signature mismatch");
        write_register(1, 65);
        write_register(8, 64'h10000);
        write_register(0, 1);
        if (!busy || config_words[1] != 65) $fatal(1, "Frame did not arm");
        write_register(1, 4096);
        if (config_words[1] != 65) $fatal(1, "Active frame config changed");
        events = 3;
        @(negedge clk);
        events = 0;
        result_valid = 1;
        @(negedge clk);
        result_valid = 0;
        repeat (3) @(negedge clk);
        if (!busy) $fatal(1, "Verdict ended the frame before DMA drain");
        engine_done = 1;
        repeat (3) @(negedge clk);
        if (busy) $fatal(1, "Drained frame did not complete");
        read_register(0, value);
        if (value != 10) $fatal(1, "Incorrect completed status %h", value);
        read_register(7, value);
        if (value != 3) $fatal(1, "Incorrect event-valid flags");
        read_register(40, value);
        if (value[31:0] != result_bits) $fatal(1, "Score not captured");
        engine_done = 0;
        write_register(12, 5);
        write_register(0, 1);
        repeat (10) @(negedge clk);
        read_register(0, value);
        if (!value[2] || !value[0]) $fatal(1, "Timeout must invalidate and hold the frame");
        $display("PASS deployment ABI: immutable config, event flags, verdict/drain and timeout");
        $finish;
    end
    initial begin
        #10000;
        $fatal(1, "Control watchdog");
    end
endmodule
