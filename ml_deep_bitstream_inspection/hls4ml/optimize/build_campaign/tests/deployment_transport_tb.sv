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
    int frame = 0;
    logic held_a = 0, held_b = 0;
    logic [31:0] held_data_a, held_data_b;
    dual_reader_ring #(.WIDTH(32), .ADDR_BITS(4)) ring (
        .clk(clk), .rst_n(rst_n), .clear(clear), .in_data(input_data),
        .in_valid(input_valid), .in_ready(input_ready),
        .a_data(a_data), .b_data(b_data), .a_valid(a_valid), .b_valid(b_valid),
        .a_ready(a_ready), .b_ready(b_ready), .written(written),
        .consumed_a(consumed_a), .consumed_b(consumed_b), .high_water(high_water)
    );
    always @(negedge clk) begin
        cycles = cycles + 1;
        input_valid = rst_n && !clear && sent < 1000;
        input_data = 32'(frame * 10000 + sent);
        if (frame == 0) begin
            a_ready = cycles % 7 != 0;
            b_ready = cycles % 11 == 0;
        end else begin
            a_ready = cycles % 13 == 0;
            b_ready = cycles % 5 != 0;
        end
    end
    always @(posedge clk) begin
        if (!rst_n || clear) begin
            held_a = 0;
            held_b = 0;
        end else begin
            if (held_a && (!a_valid || a_data !== held_data_a))
                $fatal(1, "Reader A changed under backpressure");
            if (held_b && (!b_valid || b_data !== held_data_b))
                $fatal(1, "Reader B changed under backpressure");
            held_a = a_valid && !a_ready;
            held_b = b_valid && !b_ready;
            held_data_a = a_data;
            held_data_b = b_data;
            if (input_valid && input_ready) sent = sent + 1;
            if (a_valid && a_ready) begin
                if (a_data !== 32'(frame * 10000 + seen_a))
                    $fatal(1, "Reader A order failure");
                seen_a = seen_a + 1;
            end
            if (b_valid && b_ready) begin
                if (b_data !== 32'(frame * 10000 + seen_b))
                    $fatal(1, "Reader B order failure");
                seen_b = seen_b + 1;
            end
            if (written - consumed_a > 16 || written - consumed_b > 16)
                $fatal(1, "Ring capacity exceeded");
            #1;
            if (written != sent || consumed_a != seen_a || consumed_b != seen_b)
                $fatal(1, "Ring statistics disagree with accepted transfers");
        end
    end
    initial begin
        input_data = 0;
        input_valid = 0;
        a_ready = 0;
        b_ready = 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        wait (seen_a == 1000 && seen_b == 1000);
        @(negedge clk);
        if (high_water != 16) $fatal(1, "First frame did not fill ring");
        clear = 1;
        @(negedge clk);
        frame = 1;
        sent = 0;
        seen_a = 0;
        seen_b = 0;
        clear = 0;
        wait (seen_a == 1000 && seen_b == 1000);
        @(negedge clk);
        if (high_water != 16) $fatal(1, "Second frame did not fill ring");
        $display("PASS dual-reader ring: 2 frames, 2000 words, independent stalls, full capacity, clear");
        $finish;
    end
    initial begin
        #200000;
        $fatal(1, "Ring watchdog");
    end
endmodule
