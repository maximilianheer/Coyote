`timescale 1ns/1ps
module deployment_transport_tb;
    logic clk = 0;
    always #2 clk = !clk;
    logic rst_n = 0, clear = 0;
    logic [31:0] input_data;
    logic input_valid, input_ready, a_valid, b_valid, a_ready, b_ready;
    logic [31:0] a_data, b_data;
    wire [63:0] written, consumed_a, consumed_b, high_water;
    int sent = 0, seen_a = 0, seen_b = 0, cycles = 0;
    dual_reader_ring #(.WIDTH(32), .ADDR_BITS(4)) ring (
        .clk(clk), .rst_n(rst_n), .clear(clear), .in_data(input_data),
        .in_valid(input_valid), .in_ready(input_ready),
        .a_data(a_data), .b_data(b_data), .a_valid(a_valid), .b_valid(b_valid),
        .a_ready(a_ready), .b_ready(b_ready), .written(written),
        .consumed_a(consumed_a), .consumed_b(consumed_b), .high_water(high_water)
    );
    always @(negedge clk) begin
        cycles = cycles + 1;
        input_valid = rst_n && sent < 1000;
        input_data = 32'(sent);
        a_ready = cycles % 7 != 0;
        b_ready = cycles % 11 == 0;
    end
    always @(posedge clk) begin
        if (rst_n) begin
            if (input_valid && input_ready) sent = sent + 1;
            if (a_valid && a_ready) begin
                if (a_data !== 32'(seen_a)) $fatal(1, "Reader A order failure");
                seen_a = seen_a + 1;
            end
            if (b_valid && b_ready) begin
                if (b_data !== 32'(seen_b)) $fatal(1, "Reader B order failure");
                seen_b = seen_b + 1;
            end
            if (written - consumed_a > 16 || written - consumed_b > 16)
                $fatal(1, "Ring capacity exceeded");
            if (seen_a == 1000 && seen_b == 1000) begin
                if (high_water != 16) $fatal(1, "Full-ring case not exercised");
                $display("PASS dual-reader ring: 1000 words, independent stalls, full capacity");
                $finish;
            end
        end
    end
    initial begin
        input_data = 0;
        input_valid = 0;
        a_ready = 0;
        b_ready = 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        #100000;
        $fatal(1, "Ring watchdog");
    end
endmodule
