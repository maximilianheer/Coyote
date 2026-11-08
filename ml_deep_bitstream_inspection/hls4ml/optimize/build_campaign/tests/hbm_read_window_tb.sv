`timescale 1ns/1ps
module hbm_read_window_tb;
    logic clk = 0;
    always #2 clk = !clk;
    logic rst_n = 0, start = 0, busy = 1;
    logic address_valid, address_ready, request_valid, request_ready;
    logic [63:0] address, request_address;
    logic response_valid, response_ready, word_valid, word_ready, completion;
    logic [511:0] response_data, word_data;
    wire idle, error;
    wire [63:0] issued, received, completed;
    int cycles = 0;
    hbm_read_window #(.LIMIT(3)) reader(.*);
    always @(negedge clk) begin
        cycles = cycles + 1;
        address_valid = rst_n && issued < 100;
        address = 64'h10000 + issued * 64;
        request_ready = cycles % 3 != 0;
        response_valid = rst_n && received < issued && cycles % 5 == 0;
        response_data = 512'(received);
        word_ready = cycles % 7 != 0;
        completion = rst_n && completed < issued && cycles % 2 == 0;
    end
    always @(posedge clk) begin
        if (rst_n) begin
            if (issued - received > 3 || issued - completed > 3)
                $fatal(1, "Read-credit limit exceeded");
            if (word_valid && word_ready && word_data !== 512'(received))
                $fatal(1, "Read-response data changed");
            if (error) $fatal(1, "Unexpected reader error");
            if (issued == 100 && idle) begin
                $display("PASS HBM read window: 100 reads, CQ-before-data and stalls");
                $finish;
            end
        end
    end
    initial begin
        address_valid = 0;
        request_ready = 0;
        response_valid = 0;
        response_data = 0;
        word_ready = 0;
        completion = 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        #100000;
        $fatal(1, "Reader watchdog");
    end
endmodule
