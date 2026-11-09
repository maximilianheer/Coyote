import lynxTypes::*;
`include "reader_control_instance.svh"
`include "cnn_instance.svh"

localparam TRACKING = `DEPLOY_VARIANT == 14 ? 4 : `DEPLOY_VARIANT == 16 ? 128 : 32;
logic descriptor_pending, frame_ready;
logic descriptor_valid, descriptor_ready, request_valid;
logic [95:0] descriptor;
logic [63:0] request_address;
logic [31:0] request_bytes;
logic word_valid, word_ready, memory_idle, memory_error;
logic [511:0] word_data;
logic [63:0] issued, received_words, completed, response_requests, requested_bytes;
logic [63:0] peak_outstanding, request_stalls, credit_stalls, response_backpressure;
logic [63:0] pixel_count_seen, cnn_count_seen, cnn_starvation, cnn_backpressure;
logic [63:0] peak_pixel_fifo, active_cycles, pixel_backpressure;
wire [8:0] window_limit = `DEPLOY_VARIANT == 14 ? 9'd4 :
                           `DEPLOY_VARIANT == 16 ? active_setting[8:0] : 9'd32;
wire card_completion = cq_rd.valid && cq_rd.ready && cq_rd.data.strm == STRM_CARD &&
    cq_rd.data.dest == 0 && cq_rd.data.pid == config_words[3][PID_BITS-1:0];

always_ff @(posedge aclk) begin
    if (!aresetn || start_frame) begin
        descriptor_pending <= start_frame;
        pixel_count_seen <= 0;
        cnn_count_seen <= 0;
        cnn_starvation <= 0;
        cnn_backpressure <= 0;
        peak_pixel_fifo <= 0;
        active_cycles <= 0;
        pixel_backpressure <= 0;
    end else begin
        if (descriptor_pending && frame_ready) descriptor_pending <= 0;
        if (busy) begin
            active_cycles <= active_cycles + 1;
            if (pixel_valid && pixel_ready) pixel_count_seen <= pixel_count_seen + 1;
            if (cnn_valid && cnn_ready) cnn_count_seen <= cnn_count_seen + 1;
            if (cnn_ready && !cnn_valid && cnn_count_seen < 65536)
                cnn_starvation <= cnn_starvation + 1;
            if (cnn_valid && !cnn_ready) cnn_backpressure <= cnn_backpressure + 1;
            if (pixel_valid && !pixel_ready) pixel_backpressure <= pixel_backpressure + 1;
            if ({58'b0, pixel_occupancy} > peak_pixel_fifo)
                peak_pixel_fifo <= {58'b0, pixel_occupancy};
        end
    end
end

generate
    if (`DEPLOY_VARIANT == 16) begin : individual
        logic [63:0] address;
        assign descriptor = {32'd64, address};
        hbm_gather_hls_ip gather (
            .ap_clk(aclk), .ap_rst_n(aresetn),
            .frame_TDATA({config_words[1], config_words[8]}),
            .frame_TVALID(descriptor_pending), .frame_TREADY(frame_ready),
            .addresses_TDATA(address), .addresses_TVALID(descriptor_valid),
            .addresses_TREADY(descriptor_ready), .words_TDATA(word_data),
            .words_TVALID(word_valid), .words_TREADY(word_ready),
            .pixels_TDATA(preprocessed_pixel), .pixels_TVALID(pixel_valid), .pixels_TREADY(pixel_ready)
        );
    end else if (`DEPLOY_VARIANT == 14) begin : scan
        hbm_scan_hls_ip preprocess (
            .ap_clk(aclk), .ap_rst_n(aresetn),
            .frame_TDATA({active_setting, config_words[1], config_words[8]}),
            .frame_TVALID(descriptor_pending), .frame_TREADY(frame_ready),
            .requests_TDATA(descriptor), .requests_TVALID(descriptor_valid),
            .requests_TREADY(descriptor_ready), .words_TDATA(word_data),
            .words_TVALID(word_valid), .words_TREADY(word_ready),
            .pixels_TDATA(preprocessed_pixel), .pixels_TVALID(pixel_valid), .pixels_TREADY(pixel_ready)
        );
    end else begin : coalesced
        hbm_coalesced_hls_ip preprocess (
            .ap_clk(aclk), .ap_rst_n(aresetn),
            .frame_TDATA({active_setting, config_words[1], config_words[8]}),
            .frame_TVALID(descriptor_pending), .frame_TREADY(frame_ready),
            .requests_TDATA(descriptor), .requests_TVALID(descriptor_valid),
            .requests_TREADY(descriptor_ready), .words_TDATA(word_data),
            .words_TVALID(word_valid), .words_TREADY(word_ready),
            .pixels_TDATA(preprocessed_pixel), .pixels_TVALID(pixel_valid), .pixels_TREADY(pixel_ready)
        );
    end
endgenerate

reader_window #(.TRACKING(TRACKING)) reader (
    .clk(aclk), .rst_n(aresetn), .start(start_frame), .busy(busy), .window_limit(window_limit),
    .descriptor_valid(descriptor_valid), .descriptor_ready(descriptor_ready),
    .descriptor_address(descriptor[63:0]), .descriptor_bytes(descriptor[95:64]),
    .request_valid(request_valid), .request_ready(sq_rd.ready),
    .request_address(request_address), .request_bytes(request_bytes),
    .response_valid(axis_card_recv[0].tvalid), .response_ready(axis_card_recv[0].tready),
    .response_data(axis_card_recv[0].tdata), .word_valid(word_valid), .word_ready(word_ready),
    .word_data(word_data), .completion(card_completion), .idle(memory_idle), .error(memory_error),
    .issued(issued), .received_words(received_words), .completed(completed),
    .response_requests(response_requests), .requested_bytes(requested_bytes),
    .peak_outstanding(peak_outstanding), .request_stalls(request_stalls),
    .credit_stalls(credit_stalls), .response_backpressure(response_backpressure)
);
assign engine_ready = memory_idle && !descriptor_pending;
assign engine_done = memory_idle && !descriptor_pending && pixel_count_seen == 65536;
assign engine_error = memory_error;

always_comb begin
    sq_rd.data = '0;
    sq_rd.valid = request_valid;
    sq_rd.data.opcode = LOCAL_READ;
    sq_rd.data.strm = STRM_CARD;
    sq_rd.data.pid = config_words[3][PID_BITS-1:0];
    sq_rd.data.vaddr = request_address[VADDR_BITS-1:0];
    sq_rd.data.len = request_bytes[LEN_BITS-1:0];
    sq_rd.data.last = 1;
    event_signals = 0;
    event_signals[1:0] = {2{request_valid && sq_rd.ready}};
    event_signals[3:2] = {2{word_valid && word_ready}};
    event_signals[5:4] = {2{pixel_valid && pixel_ready}};
    event_signals[7:6] = {2{cnn_valid && cnn_ready}};
    event_signals[9:8] = {2{result_valid}};
    event_signals[11:10] = {2{card_completion}};
    transport_counters[0] = issued;
    transport_counters[1] = received_words;
    transport_counters[2] = completed;
    transport_counters[3] = pixel_count_seen;
    transport_counters[4] = {58'b0, pixel_occupancy};
    transport_counters[5] = requested_bytes;
    transport_counters[6] = peak_outstanding;
    transport_counters[7] = request_stalls;
    transport_counters[8] = credit_stalls;
    transport_counters[9] = response_backpressure;
    transport_counters[10] = cnn_starvation;
    transport_counters[11] = cnn_backpressure;
    transport_counters[12] = peak_pixel_fifo;
    transport_counters[13] = active_cycles;
    transport_counters[14] = pixel_backpressure;
    transport_counters[15] = response_requests;
end
always_comb sq_wr.tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb axis_card_send[0].tie_off_m();
always_comb axis_host_send[0].tie_off_m();
always_comb axis_host_send[1].tie_off_m();
always_comb axis_host_recv[0].tie_off_s();
always_comb axis_host_recv[1].tie_off_s();
always_comb notify.tie_off_m();
wire benchmark_debug_activity = word_valid && word_ready;
`include "debug_probe.svh"
