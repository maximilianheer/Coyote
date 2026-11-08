import lynxTypes::*;
`define DEPLOY_VARIANT 10
`include "control_instance.svh"
`include "cnn_instance.svh"

logic descriptor_pending, descriptor_ready;
logic address_valid, address_ready, request_valid;
logic [63:0] sample_address, request_address;
logic word_valid, word_ready, memory_idle, memory_error;
logic [511:0] word_data;
logic [63:0] issued, received, completed, pixel_count_seen;
wire card_completion = cq_rd.valid && cq_rd.ready && cq_rd.data.strm == STRM_CARD &&
    cq_rd.data.dest == 0 && cq_rd.data.pid == config_words[3][PID_BITS-1:0];

always_ff @(posedge aclk) begin
    if (!aresetn) begin
        descriptor_pending <= 0;
        pixel_count_seen <= 0;
    end else begin
        if (descriptor_pending && descriptor_ready) descriptor_pending <= 0;
        if (pixel_valid && pixel_ready) pixel_count_seen <= pixel_count_seen + 1;
        if (start_frame) begin
            descriptor_pending <= 1;
            pixel_count_seen <= 0;
        end
    end
end
hbm_gather_hls_ip gather (
    .ap_clk(aclk), .ap_rst_n(aresetn),
    .frame_TDATA({config_words[1], config_words[8]}),
    .frame_TVALID(descriptor_pending), .frame_TREADY(descriptor_ready),
    .addresses_TDATA(sample_address), .addresses_TVALID(address_valid), .addresses_TREADY(address_ready),
    .words_TDATA(word_data), .words_TVALID(word_valid), .words_TREADY(word_ready),
    .pixels_TDATA(preprocessed_pixel), .pixels_TVALID(pixel_valid), .pixels_TREADY(pixel_ready)
);
hbm_read_window reader (
    .clk(aclk), .rst_n(aresetn), .start(start_frame), .busy(busy),
    .address_valid(address_valid), .address_ready(address_ready), .address(sample_address),
    .request_valid(request_valid), .request_ready(sq_rd.ready), .request_address(request_address),
    .response_valid(axis_card_recv[0].tvalid), .response_ready(axis_card_recv[0].tready),
    .response_data(axis_card_recv[0].tdata), .word_valid(word_valid), .word_ready(word_ready),
    .word_data(word_data), .completion(card_completion),
    .idle(memory_idle), .error(memory_error), .issued(issued), .received(received), .completed(completed)
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
    sq_rd.data.len = 64;
    sq_rd.data.last = 1;
    event_signals = 0;
    event_signals[1:0] = {2{request_valid && sq_rd.ready}};
    event_signals[3:2] = {2{word_valid && word_ready}};
    event_signals[5:4] = {2{pixel_valid && pixel_ready}};
    event_signals[7:6] = {2{cnn_valid && cnn_ready}};
    event_signals[9:8] = {2{result_valid}};
    event_signals[11:10] = {2{card_completion}};
    for (int i = 0; i < 16; i++) transport_counters[i] = 0;
    transport_counters[0] = issued;
    transport_counters[1] = received;
    transport_counters[2] = completed;
    transport_counters[3] = pixel_count_seen;
    transport_counters[4] = {58'b0, pixel_occupancy};
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
`undef DEPLOY_VARIANT
