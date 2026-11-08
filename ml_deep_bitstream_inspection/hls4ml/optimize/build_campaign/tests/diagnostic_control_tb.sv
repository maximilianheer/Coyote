`timescale 1ns/1ps
module diagnostic_control_tb;
    logic clk = 0;
    always #2 clk = !clk;
    logic rst_n = 0;
    logic [63:0] awaddr = 0, araddr = 0, wdata = 0, rdata;
    logic [7:0] wstrb = 0;
    logic awvalid = 0, wvalid = 0, bready = 1;
    logic arvalid = 0, rready = 1;
    wire awready, wready, bvalid, arready, rvalid;
    wire [1:0] bresp, rresp;
    logic request = 0, complete = 0, payload = 0, blocked = 0;
    logic [63:0] keep = 0;
    wire card_mode;
    diagnostic_control dut(.*);

    task automatic read_check(input [63:0] address, expected);
        @(negedge clk);
        araddr = address;
        arvalid = 1;
        @(negedge clk);
        arvalid = 0;
        if (!rvalid || rdata !== expected)
            $fatal(1, "CSR %d got %h expected %h", address / 8, rdata, expected);
        @(negedge clk);
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        read_check(0, 64'h4e45544400010000);
        read_check(24, 0);
        @(negedge clk);
        request = 1;
        payload = 1;
        keep = 64'hffffffffffffffff;
        @(negedge clk);
        request = 0;
        keep = 64'h7;
        @(negedge clk);
        payload = 0;
        complete = 1;
        @(negedge clk);
        complete = 0;
        read_check(24, 67);
        read_check(32, 1);
        read_check(40, 1);
        // AXI address and data can arrive independently.
        awaddr = 16;
        awvalid = 1;
        @(negedge clk);
        awvalid = 0;
        repeat (2) @(negedge clk);
        wdata = 1;
        wstrb = 1;
        wvalid = 1;
        @(negedge clk);
        wvalid = 0;
        repeat (3) @(negedge clk);
        read_check(16, 1);
        $display("PASS diagnostic control counters, partial keep and split AXI write");
        $finish;
    end
    initial begin
        #10000;
        $fatal(1, "watchdog");
    end
endmodule
