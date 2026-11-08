`timescale 1ns/1ps
module hbm_forward_tb;
    logic clk = 0;
    always #2 clk = !clk;
    logic rst_n = 0, start = 0;
    logic [63:0] length = 0, hbm_base = 64'h10000, gpu_base = 64'h20000;
    wire rd_valid, wr_valid, input_ready, output_valid, output_last, idle, done, error;
    logic rd_ready = 0, wr_ready = 0, input_valid = 0, output_ready = 0;
    wire [63:0] rd_address, wr_address, output_keep, bytes_sent, chunks_completed;
    wire [27:0] request_length;
    logic [511:0] input_data = 0;
    wire [511:0] output_data;
    logic rd_complete = 0, wr_complete = 0;
    int cycle = 0, pending_words = 0, word_index = 0;
    logic read_inflight = 0, write_inflight = 0;
    logic [63:0] requested_read = 0, requested_write = 0, write_target = 0;
    hbm_forward forwarder(.*);

    always @(negedge clk) begin
        cycle = cycle + 1;
        rd_ready = cycle % 3 != 0;
        wr_ready = cycle % 5 != 0;
        input_valid = pending_words > 0 && cycle % 7 != 0;
        input_data = 512'(word_index);
        output_ready = cycle % 4 != 0;
        rd_complete = read_inflight && cycle % 11 == 0;
        wr_complete = write_inflight && bytes_sent == write_target && cycle % 13 == 0;
    end
    always @(posedge clk) begin
        if (rst_n && !start) begin
            if (rd_valid && rd_ready) begin
                if (rd_address != hbm_base + requested_read || request_length == 0)
                    $fatal(1, "Incorrect HBM burst address/length");
                requested_read = requested_read + request_length;
                pending_words = pending_words + int'((request_length + 63) / 64);
                read_inflight = 1;
            end
            if (wr_valid && wr_ready) begin
                if (wr_address != gpu_base + 64 + requested_write)
                    $fatal(1, "Incorrect GPU burst address");
                requested_write = requested_write + request_length;
                write_target = requested_write;
                write_inflight = 1;
            end
            if (input_valid && input_ready) begin
                if (output_data !== 512'(word_index)) $fatal(1, "Corrupted forwarded word");
                pending_words = pending_words - 1;
                word_index = word_index + 1;
            end
            if (rd_complete) read_inflight = 0;
            if (wr_complete) write_inflight = 0;
            if (error) $fatal(1, "Forwarder error");
        end
    end

    task automatic frame(input logic [63:0] size);
        @(negedge clk);
        length = size;
        pending_words = 0;
        word_index = 0;
        read_inflight = 0;
        write_inflight = 0;
        requested_read = 0;
        requested_write = 0;
        start = 1;
        @(negedge clk);
        start = 0;
        wait(done);
        @(negedge clk);
        if (bytes_sent != size || requested_read != size || requested_write != size || pending_words != 0)
            $fatal(1, "Incomplete frame size=%d sent=%d", size, bytes_sent);
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        frame(0);
        frame(1);
        frame(63);
        frame(64);
        frame(65);
        frame(65535);
        frame(65536);
        frame(65537);
        frame(131073);
        $display("PASS HBM forward: tails, independent stalls, early read CQ, consecutive frames");
        $finish;
    end
    initial begin
        #1000000;
        $fatal(1, "Forwarder watchdog");
    end
endmodule
