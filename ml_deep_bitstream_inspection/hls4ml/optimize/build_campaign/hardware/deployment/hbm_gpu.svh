import lynxTypes::*;
`define DEPLOY_VARIANT 11
`include "control_instance.svh"

logic rd_valid, wr_valid, forward_idle, forward_done, forward_error;
logic [63:0] rd_address, wr_address, bytes_sent, chunks_completed;
logic [27:0] request_length;
logic poll_valid, poll_ready, poll_active, poll_error;
logic [63:0] poll_address, result_trial, poll_stats [9];
wire hbm_ack = cq_rd.valid && cq_rd.ready && cq_rd.data.strm == STRM_CARD &&
    cq_rd.data.dest == 0 && cq_rd.data.pid == config_words[3][PID_BITS-1:0];
wire gpu_ack = cq_wr.valid && cq_wr.ready && cq_wr.data.strm == STRM_HOST &&
    cq_wr.data.dest == 0 && !cq_wr.data.host &&
    cq_wr.data.pid == config_words[3][PID_BITS-1:0];
wire poll_ack = cq_rd.valid && cq_rd.ready && cq_rd.data.strm == STRM_HOST &&
    cq_rd.data.dest == 1 && !cq_rd.data.host &&
    cq_rd.data.pid == config_words[3][PID_BITS-1:0];

hbm_forward forwarder (
    .clk(aclk), .rst_n(aresetn), .start(start_frame),
    .length(config_words[1]), .hbm_base(config_words[8]), .gpu_base(config_words[9]),
    .rd_valid(rd_valid), .rd_ready(sq_rd.ready && !poll_valid),
    .wr_valid(wr_valid), .wr_ready(sq_wr.ready),
    .rd_address(rd_address), .wr_address(wr_address), .request_length(request_length),
    .input_valid(axis_card_recv[0].tvalid), .input_ready(axis_card_recv[0].tready),
    .input_data(axis_card_recv[0].tdata),
    .output_valid(axis_host_send[0].tvalid), .output_ready(axis_host_send[0].tready),
    .output_data(axis_host_send[0].tdata), .output_keep(axis_host_send[0].tkeep),
    .output_last(axis_host_send[0].tlast), .rd_complete(hbm_ack), .wr_complete(gpu_ack),
    .idle(forward_idle), .done(forward_done), .error(forward_error),
    .bytes_sent(bytes_sent), .chunks_completed(chunks_completed)
);
assign axis_host_send[0].tid = config_words[3][PID_BITS-1:0];
gpu_poll poller (
    .clk(aclk), .rst_n(aresetn), .busy(busy), .input_done(forward_done), .tick(tick),
    .ready_addr(config_words[10]), .payload_addr(config_words[11]),
    .trial(config_words[2]), .gap_cycles(config_words[13][31:0]),
    .req_valid(poll_valid), .req_ready(sq_rd.ready), .req_addr(poll_address),
    .rsp_valid(axis_host_recv[1].tvalid), .rsp_ready(axis_host_recv[1].tready),
    .rsp_data(axis_host_recv[1].tdata),
    .rsp_wellformed(axis_host_recv[1].tkeep == ~64'b0 && axis_host_recv[1].tlast &&
        axis_host_recv[1].tid == config_words[3][PID_BITS-1:0]),
    .ack(poll_ack), .active(poll_active), .fatal(poll_error),
    .result_valid(result_valid), .result_bits(result_bits),
    .result_trial(result_trial), .stats(poll_stats)
);
assign engine_ready = forward_idle && !poll_active;
assign engine_done = forward_done && !poll_active;
assign engine_error = forward_error || poll_error;

always_comb begin
    sq_rd.data = '0;
    sq_rd.valid = poll_valid || rd_valid;
    sq_rd.data.opcode = LOCAL_READ;
    sq_rd.data.strm = poll_valid ? STRM_HOST : STRM_CARD;
    sq_rd.data.dest = poll_valid ? 1 : 0;
    sq_rd.data.pid = config_words[3][PID_BITS-1:0];
    sq_rd.data.vaddr = poll_valid ? VADDR_BITS'(poll_address) : VADDR_BITS'(rd_address);
    sq_rd.data.len = poll_valid ? LEN_BITS'(64) : LEN_BITS'(request_length);
    sq_rd.data.last = 1;
    sq_wr.data = '0;
    sq_wr.valid = wr_valid;
    sq_wr.data.opcode = LOCAL_WRITE;
    sq_wr.data.strm = STRM_HOST;
    sq_wr.data.pid = config_words[3][PID_BITS-1:0];
    sq_wr.data.vaddr = wr_address[VADDR_BITS-1:0];
    sq_wr.data.len = request_length;
    sq_wr.data.last = 1;
    event_signals = 0;
    event_signals[1:0] = {2{rd_valid && sq_rd.ready}};
    event_signals[3:2] = {2{axis_card_recv[0].tvalid && axis_card_recv[0].tready}};
    event_signals[9:8] = {2{result_valid}};
    event_signals[11:10] = {2{hbm_ack}};
    event_signals[13:12] = {2{axis_host_send[0].tvalid && axis_host_send[0].tready}};
    event_signals[15:14] = {2{gpu_ack}};
    event_signals[17:16] = {2{poll_valid && sq_rd.ready}};
    for (int i = 0; i < 16; i++) transport_counters[i] = 0;
    transport_counters[0] = bytes_sent;
    transport_counters[1] = chunks_completed;
    for (int i = 0; i < 9; i++) transport_counters[4+i] = poll_stats[i];
end
always_comb axis_card_send[0].tie_off_m();
always_comb axis_host_send[1].tie_off_m();
always_comb axis_host_recv[0].tie_off_s();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb notify.tie_off_m();
wire benchmark_debug_activity = axis_host_send[0].tvalid && axis_host_send[0].tready;
`include "debug_probe.svh"
`undef DEPLOY_VARIANT
