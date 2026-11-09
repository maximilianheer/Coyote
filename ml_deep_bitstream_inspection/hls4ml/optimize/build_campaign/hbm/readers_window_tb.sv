`timescale 1ns/1ps
`ifndef TRACKING_VALUE
`define TRACKING_VALUE 128
`endif
module readers_window_tb;
    logic clk = 0;
    always #2 clk = !clk;
    logic rst_n = 0, start = 0, busy = 1;
    logic [8:0] window_limit = 4;
    logic descriptor_valid, descriptor_ready, request_valid, request_ready;
    logic [63:0] descriptor_address, request_address;
    logic [31:0] descriptor_bytes, request_bytes;
    logic response_valid, response_ready, word_valid, word_ready, completion;
    logic [511:0] response_data, word_data;
    wire idle, error;
    wire [63:0] issued, received_words, completed, response_requests;
    wire [63:0] requested_bytes, peak_outstanding, request_stalls, credit_stalls, response_backpressure;
    int cycles = 0;
    int run_number = 0;
    int model_request = 0, model_beat = 0;
    logic ready_sink = 0;
    reader_window #(.TRACKING(`TRACKING_VALUE)) reader(.*);

    function automatic int size_for(input int index);
        case (index % 5)
            0: return 1;
            1: return 65;
            2: return 4096;
            3: return 16384;
            default: return 65536;
        endcase
    endfunction

    always @(negedge clk) begin
        cycles = cycles + 1;
        descriptor_valid = rst_n && issued < 300;
        descriptor_address = 64'h400000 + issued * 65536;
        descriptor_bytes = size_for(int'(issued));
        request_ready = ready_sink || cycles % 7 != 0;
        response_valid = rst_n && response_requests < issued && (ready_sink || cycles % 5 != 0);
        response_data = 512'(received_words);
        word_ready = ready_sink || cycles % 3 != 0;
        // CQ may precede the first data beat, or lag data in the other mode.
        completion = rst_n && completed < issued && (ready_sink ? cycles % 17 == 0 : cycles % 2 == 0);
    end

    always @(posedge clk) begin
        if (!rst_n || start) begin
            model_request = 0;
            model_beat = 0;
        end else begin
            if (issued - response_requests > window_limit || issued - completed > window_limit)
                $fatal(1, "Outstanding credit exceeded");
            if (request_valid && request_ready &&
                (request_bytes != size_for(int'(issued)) || request_address != descriptor_address))
                $fatal(1, "Request descriptor changed");
            if (word_valid && word_ready) begin
                if (word_data !== 512'(received_words)) $fatal(1, "Response data reordered");
                model_beat++;
                if (model_beat == (size_for(model_request) + 63) / 64) begin
                    model_beat = 0;
                    model_request++;
                end
            end
            if (response_requests > model_request) $fatal(1, "Premature response retirement");
            if (peak_outstanding > window_limit) $fatal(1, "Incorrect peak credit count");
            if (error) $fatal(1, "Unexpected reader error");
        end
    end

    task automatic frame(input int window, input bit sink);
        @(posedge clk);
        rst_n = 0;
        window_limit = 9'(window);
        ready_sink = sink;
        repeat (3) @(posedge clk);
        @(negedge clk);
        rst_n = 1;
        wait (issued == 300 && idle);
        @(negedge clk);
        if (response_requests != 300 || completed != 300 || model_request != 300)
            $fatal(1, "Incomplete descriptor/data/CQ drain");
        run_number++;
        $display("PASS reader frame window=%0d ready_sink=%0d words=%0d peak=%0d", window, sink, received_words, peak_outstanding);
    endtask

    initial begin
        descriptor_valid = 0;
        descriptor_address = 0;
        descriptor_bytes = 0;
        request_ready = 0;
        response_valid = 0;
        response_data = 0;
        word_ready = 0;
        completion = 0;
        frame(4, 0);
        frame(4, 1);
        if (`TRACKING_VALUE == 128) begin
            frame(32, 0);
            frame(64, 0);
            frame(128, 0);
            frame(128, 1);
        end
        $display("PASS reader window independent beats/CQ, partial chunks, resets, stalls and always-ready sink");
        $finish;
    end
    initial begin
        #30000000;
        $fatal(1, "Reader simulation watchdog");
    end
endmodule
