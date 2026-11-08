import lynxTypes::*;
`include "control_instance.svh"

logic [576:0] store_data, inspect_data;
logic store_valid, store_ready, inspect_valid, inspect_ready;
logic [63:0] ring_written, store_consumed, inspect_consumed, ring_peak;
logic ring_ready;
logic [63:0] received_bytes, requested_bytes, hbm_requests, hbm_completions;
logic [63:0] gpu_posted_bytes, gpu_requests, gpu_completions, gpu_words;
logic [63:0] net_stalls, store_stalls, inspect_stalls;
logic frame_error;
logic [6:0] valid_bytes;
logic descriptor_pending, descriptor_ready;
logic poll_active, poll_fatal, poll_valid;
logic [63:0] poll_address, poll_result_trial, poll_stats [9];
logic [127:0] store_request, gpu_request;
logic store_request_ready, gpu_request_ready, gpu_request_valid;
logic arb_valid;
logic [127:0] arb_data;
wire request_bad = rq_wr.data.pid != config_words[3][PID_BITS-1:0] ||
    rq_wr.data.vaddr != VADDR_BITS'(config_words[8] + requested_bytes) ||
    rq_wr.data.len == 0 || requested_bytes + rq_wr.data.len > config_words[1];
wire accept_request = rq_wr.valid && rq_wr.ready;
wire accepted_payload = axis_rrsp_recv[0].tvalid && axis_rrsp_recv[0].tready;
wire store_ack = cq_wr.valid && cq_wr.ready && cq_wr.data.strm == STRM_CARD &&
    cq_wr.data.dest == 0 && cq_wr.data.pid == config_words[3][PID_BITS-1:0];
wire gpu_ack = cq_wr.valid && cq_wr.ready && cq_wr.data.strm == STRM_HOST &&
    cq_wr.data.dest == 0 && !cq_wr.data.host &&
    cq_wr.data.pid == config_words[3][PID_BITS-1:0];
wire poll_ack = cq_rd.valid && cq_rd.ready && cq_rd.data.strm == STRM_HOST &&
    cq_rd.data.dest == 1 && !cq_rd.data.host &&
    cq_rd.data.pid == config_words[3][PID_BITS-1:0];
wire [63:0] expected_words = (config_words[1] + 63) >> 6;
wire [63:0] released_words = store_consumed < inspect_consumed ? store_consumed : inspect_consumed;
wire transfer_drained = received_bytes == config_words[1] &&
    requested_bytes == config_words[1] && store_consumed == expected_words &&
    inspect_consumed == expected_words && hbm_completions == hbm_requests &&
    (!config_words[1] || hbm_requests != 0) && !arb_valid;

dual_reader_ring ring (
    .clk(aclk), .rst_n(aresetn), .clear(start_frame),
    .in_data({axis_rrsp_recv[0].tlast, axis_rrsp_recv[0].tkeep, axis_rrsp_recv[0].tdata}),
    .in_valid(axis_rrsp_recv[0].tvalid && busy && !frame_error), .in_ready(ring_ready),
    .a_data(store_data), .a_valid(store_valid), .a_ready(store_ready),
    .b_data(inspect_data), .b_valid(inspect_valid), .b_ready(inspect_ready),
    .written(ring_written), .consumed_a(store_consumed), .consumed_b(inspect_consumed),
    .high_water(ring_peak)
);
assign axis_rrsp_recv[0].tready = ring_ready && busy && !frame_error;
assign axis_card_send[0].tvalid = store_valid;
assign axis_card_send[0].tdata = store_data[511:0];
assign axis_card_send[0].tkeep = store_data[575:512];
assign axis_card_send[0].tlast = store_data[576];
assign axis_card_send[0].tid = config_words[3][PID_BITS-1:0];
assign store_ready = axis_card_send[0].tready;
assign rq_wr.ready = store_request_ready && busy && !request_bad && !frame_error;

req_t native_store, generated_gpu;
always_comb begin
    native_store = rq_wr.data;
    native_store.strm = STRM_CARD;
    native_store.dest = 0;
    store_request = native_store;
    generated_gpu = '0;
    generated_gpu.opcode = LOCAL_WRITE;
    generated_gpu.strm = STRM_HOST;
    generated_gpu.pid = config_words[3][PID_BITS-1:0];
    generated_gpu.vaddr = VADDR_BITS'(config_words[9] + 64 + gpu_posted_bytes);
    generated_gpu.len = config_words[1] - gpu_posted_bytes > 65536
        ? LEN_BITS'(65536) : LEN_BITS'(config_words[1] - gpu_posted_bytes);
    generated_gpu.last = 1;
    gpu_request = generated_gpu;
    valid_bytes = 0;
    for (int lane = 0; lane < 64; lane++)
        valid_bytes = valid_bytes + {6'b0, axis_rrsp_recv[0].tkeep[lane]};
end
request_arbiter writes (
    .clk(aclk), .rst_n(aresetn),
    .a_data(store_request), .a_valid(rq_wr.valid && busy && !request_bad && !frame_error),
    .a_ready(store_request_ready), .b_data(gpu_request), .b_valid(gpu_request_valid),
    .b_ready(gpu_request_ready), .out_data(arb_data), .out_valid(arb_valid), .out_ready(sq_wr.ready)
);
assign sq_wr.valid = arb_valid;
assign sq_wr.data = req_t'(arb_data);

always_ff @(posedge aclk) begin
    if (!aresetn || start_frame) begin
        received_bytes <= 0;
        requested_bytes <= 0;
        hbm_requests <= 0;
        hbm_completions <= 0;
        gpu_posted_bytes <= 0;
        gpu_requests <= 0;
        gpu_completions <= 0;
        gpu_words <= 0;
        net_stalls <= 0;
        store_stalls <= 0;
        inspect_stalls <= 0;
        frame_error <= 0;
        descriptor_pending <= start_frame;
    end else begin
        if (descriptor_pending && descriptor_ready) descriptor_pending <= 0;
        if (busy && rq_wr.valid && request_bad) frame_error <= 1;
        if (busy && rq_rd.valid) frame_error <= 1;
        if (accept_request) begin
            requested_bytes <= requested_bytes + rq_wr.data.len;
            if (rq_wr.data.last) hbm_requests <= hbm_requests + 1;
        end
        if (store_ack) begin
            hbm_completions <= hbm_completions + 1;
            if (hbm_completions >= hbm_requests) frame_error <= 1;
        end
        if (gpu_ack) begin
            gpu_completions <= gpu_completions + 1;
            if (gpu_completions >= gpu_requests) frame_error <= 1;
        end
        if (gpu_request_valid && gpu_request_ready) begin
            gpu_posted_bytes <= gpu_posted_bytes + generated_gpu.len;
            gpu_requests <= gpu_requests + 1;
        end
        if (axis_host_send[0].tvalid && axis_host_send[0].tready) gpu_words <= gpu_words + 1;
        if (accepted_payload) begin
            received_bytes <= received_bytes + {57'b0, valid_bytes};
            if (valid_bytes == 0 || received_bytes + {57'b0, valid_bytes} > config_words[1] ||
                (axis_rrsp_recv[0].tkeep & (axis_rrsp_recv[0].tkeep + 64'd1)) != 0 ||
                (valid_bytes != 64 && received_bytes + {57'b0, valid_bytes} != config_words[1]))
                frame_error <= 1;
        end
        if (busy && axis_rrsp_recv[0].tvalid && !axis_rrsp_recv[0].tready) net_stalls <= net_stalls + 1;
        if (store_valid && !store_ready) store_stalls <= store_stalls + 1;
        if (inspect_valid && !inspect_ready) inspect_stalls <= inspect_stalls + 1;
    end
end

`ifdef DEPLOY_CNN
    `include "cnn_instance.svh"
    network_preprocess_hls_ip preprocess (
        .ap_clk(aclk), .ap_rst_n(aresetn),
        .lengths_TDATA(config_words[1]), .lengths_TVALID(descriptor_pending), .lengths_TREADY(descriptor_ready),
        .raw_TDATA(inspect_data[511:0]), .raw_TKEEP(inspect_data[575:512]),
        .raw_TSTRB(inspect_data[575:512]), .raw_TLAST(inspect_data[576]),
        .raw_TVALID(inspect_valid), .raw_TREADY(inspect_ready),
        .pixels_TDATA(preprocessed_pixel), .pixels_TVALID(pixel_valid), .pixels_TREADY(pixel_ready)
    );
    assign engine_done = transfer_drained && !descriptor_pending;
    assign engine_ready = !descriptor_pending && !store_valid && !inspect_valid && !arb_valid;
    assign engine_error = frame_error;
    assign gpu_request_valid = 0;
    assign poll_active = 0;
    assign poll_fatal = 0;
    assign poll_valid = 0;
    for (genvar i = 0; i < 9; i++) assign poll_stats[i] = 0;
    always_comb sq_rd.tie_off_m();
    always_comb axis_host_recv[1].tie_off_s();
    always_comb axis_host_send[0].tie_off_m();
`else
    assign descriptor_ready = 1;
    assign gpu_request_valid = busy && !frame_error && gpu_posted_bytes < config_words[1] &&
        gpu_requests - gpu_completions < config_words[15];
    assign axis_host_send[0].tvalid = inspect_valid;
    assign inspect_ready = axis_host_send[0].tready;
    assign axis_host_send[0].tdata = inspect_data[511:0];
    assign axis_host_send[0].tkeep = inspect_data[575:512];
    assign axis_host_send[0].tlast = gpu_words[9:0] == 1023 || gpu_words + 1 == expected_words;
    assign axis_host_send[0].tid = config_words[3][PID_BITS-1:0];
    assign engine_done = transfer_drained && gpu_requests == gpu_completions && !poll_active;
    assign engine_ready = !descriptor_pending && !store_valid && !inspect_valid && !arb_valid && !poll_active;
    assign engine_error = frame_error || poll_fatal;
    gpu_poll poller (
        .clk(aclk), .rst_n(aresetn), .busy(busy),
        .input_done(transfer_drained && gpu_posted_bytes == config_words[1] && gpu_requests == gpu_completions),
        .tick(tick), .ready_addr(config_words[10]), .payload_addr(config_words[11]),
        .trial(config_words[2]), .gap_cycles(config_words[13][31:0]),
        .req_valid(poll_valid), .req_ready(sq_rd.ready), .req_addr(poll_address),
        .rsp_valid(axis_host_recv[1].tvalid), .rsp_ready(axis_host_recv[1].tready),
        .rsp_data(axis_host_recv[1].tdata),
        .rsp_wellformed(axis_host_recv[1].tkeep == ~64'b0 && axis_host_recv[1].tlast &&
            axis_host_recv[1].tid == config_words[3][PID_BITS-1:0]),
        .ack(poll_ack), .active(poll_active), .fatal(poll_fatal),
        .result_valid(result_valid), .result_bits(result_bits),
        .result_trial(poll_result_trial), .stats(poll_stats)
    );
    always_comb begin
        sq_rd.data = '0;
        sq_rd.valid = poll_valid;
        sq_rd.data.opcode = LOCAL_READ;
        sq_rd.data.strm = STRM_HOST;
        sq_rd.data.dest = 1;
        sq_rd.data.pid = config_words[3][PID_BITS-1:0];
        sq_rd.data.vaddr = poll_address[VADDR_BITS-1:0];
        sq_rd.data.len = 64;
        sq_rd.data.last = 1;
    end
`endif

always_comb begin
    event_signals = 0;
    event_signals[1:0] = {2{busy && axis_rrsp_recv[0].tvalid}};
    event_signals[3:2] = {2{accepted_payload}};
    event_signals[9:8] = {2{result_valid}};
    event_signals[11:10] = {2{store_valid && store_ready}};
    event_signals[13:12] = {2{axis_host_send[0].tvalid && axis_host_send[0].tready}};
    event_signals[15:14] = {2{gpu_ack}};
    event_signals[17:16] = {2{poll_valid && sq_rd.ready}};
    event_signals[19:18] = {2{store_ack}};
    event_signals[21:20] = {2{accept_request}};
`ifdef DEPLOY_CNN
    event_signals[5:4] = {2{pixel_valid && pixel_ready}};
    event_signals[7:6] = {2{cnn_valid && cnn_ready}};
`endif
    for (int i = 0; i < 16; i++) transport_counters[i] = 0;
    transport_counters[0] = received_bytes;
    transport_counters[1] = requested_bytes;
    transport_counters[2] = hbm_requests;
    transport_counters[3] = hbm_completions;
    transport_counters[4] = gpu_words;
    transport_counters[5] = gpu_requests;
    transport_counters[6] = gpu_completions;
    transport_counters[7] = released_words == expected_words
        ? (config_words[1] + 65535) >> 16 : released_words >> 10;
    transport_counters[8] = ring_peak;
    transport_counters[9] = net_stalls;
    transport_counters[10] = store_stalls;
    transport_counters[11] = inspect_stalls;
    transport_counters[12] = {63'b0, frame_error};
    transport_counters[13] = poll_stats[4];
    transport_counters[14] = poll_stats[2];
    transport_counters[15] = poll_stats[3];
end
always_comb rq_rd.tie_off_s();
always_comb axis_rreq_recv[0].tie_off_s();
always_comb axis_rreq_send[0].tie_off_m();
always_comb axis_rrsp_send[0].tie_off_m();
always_comb axis_card_recv[0].tie_off_s();
always_comb axis_host_recv[0].tie_off_s();
always_comb axis_host_send[1].tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb notify.tie_off_m();
wire benchmark_debug_activity = accepted_payload;
`include "debug_probe.svh"
