import lynxTypes::*;
`include "benchmark_variant.svh"
logic bench_req_valid, bench_busy;
logic [31:0] pp_start, pp_end, cnn_start, logit, produced_tokens;
logic [63:0] bench_addr;
logic [31:0] bench_bytes, bench_pid;
logic [2:0] bench_phase;
logic [31:0] bench_phase_word;
logic [511:0] bench_result;
logic bench_result_valid;
logic bench_input_ready;
benchmark_control #(.ADDR_BITS($bits(axi_ctrl.awaddr)), .DATA_BITS($bits(axi_ctrl.wdata)),
    .INSTRUMENT(BENCH_INSTRUMENT), .VARIANT(BENCH_VARIANT)) inst_benchmark_control (
    .clk(aclk), .rst_n(aresetn),
    .awaddr(axi_ctrl.awaddr), .awvalid(axi_ctrl.awvalid), .awready(axi_ctrl.awready),
    .wdata(axi_ctrl.wdata), .wstrb(axi_ctrl.wstrb), .wvalid(axi_ctrl.wvalid), .wready(axi_ctrl.wready),
    .bvalid(axi_ctrl.bvalid), .bready(axi_ctrl.bready), .bresp(axi_ctrl.bresp),
    .araddr(axi_ctrl.araddr), .arvalid(axi_ctrl.arvalid), .arready(axi_ctrl.arready),
    .rdata(axi_ctrl.rdata), .rvalid(axi_ctrl.rvalid), .rready(axi_ctrl.rready), .rresp(axi_ctrl.rresp),
    .request_valid(bench_req_valid), .request_ready(sq_rd.ready),
    .read_complete(cq_rd.valid && cq_rd.ready),
    .source_addr(bench_addr), .source_bytes(bench_bytes), .source_pid(bench_pid),
    .in_valid(axis_card_recv[0].tvalid && bench_busy), .in_ready(bench_input_ready),
    .stage_events({logit[0], cnn_start[0], pp_end[0], pp_start[0]}),
    .produced_tokens(produced_tokens), .phase(bench_phase), .result_valid(bench_result_valid), .result_bits(bench_result[31:0]),
    .busy(bench_busy)
);
always_comb begin
    sq_rd.data = '0;
    sq_rd.data.opcode = LOCAL_READ;
    sq_rd.data.strm = STRM_CARD;
    sq_rd.data.pid = bench_pid[PID_BITS-1:0];
    sq_rd.data.dest = '0;
    sq_rd.data.last = 1'b1;
    sq_rd.data.vaddr = bench_addr[VADDR_BITS-1:0];
    sq_rd.data.len = bench_bytes[LEN_BITS-1:0];
    sq_rd.valid = bench_req_valid;
end
assign axis_card_recv[0].tready = bench_input_ready && bench_busy;
generate if (BENCH_VARIANT == 6) begin : streaming_model
model_wrapper_hls_ip inst_model (
    .data_in_TDATA(axis_card_recv[0].tdata), .data_in_TKEEP(axis_card_recv[0].tkeep),
    .data_in_TLAST(axis_card_recv[0].tlast), .data_in_TSTRB(64'b0),
    .data_in_TVALID(axis_card_recv[0].tvalid && bench_busy), .data_in_TREADY(bench_input_ready),
    .data_out_TDATA(bench_result), .data_out_TKEEP(), .data_out_TLAST(), .data_out_TSTRB(),
    .data_out_TVALID(bench_result_valid), .data_out_TREADY(1'b1),
    .pp_start(pp_start), .pp_end(pp_end), .cnn_start(cnn_start),
    .logit(logit), .produced_tokens(produced_tokens),
    .ap_clk(aclk), .ap_rst_n(aresetn)
);
assign bench_phase_word = 0;
assign bench_phase = 0;
end else if (BENCH_INSTRUMENT) begin : instrumented_model
model_wrapper_hls_ip inst_model (
    .data_in_TDATA(axis_card_recv[0].tdata), .data_in_TKEEP(axis_card_recv[0].tkeep),
    .data_in_TLAST(axis_card_recv[0].tlast), .data_in_TSTRB(64'b0),
    .data_in_TVALID(axis_card_recv[0].tvalid && bench_busy), .data_in_TREADY(bench_input_ready),
    .data_out_TDATA(bench_result), .data_out_TKEEP(), .data_out_TLAST(), .data_out_TSTRB(),
    .data_out_TVALID(bench_result_valid), .data_out_TREADY(1'b1),
    .phase(bench_phase_word),
    .ap_clk(aclk), .ap_rst_n(aresetn)
);
assign bench_phase = bench_phase_word[2:0];
end else begin : uninstrumented_model
model_wrapper_hls_ip inst_model (
    .data_in_TDATA(axis_card_recv[0].tdata), .data_in_TKEEP(axis_card_recv[0].tkeep),
    .data_in_TLAST(axis_card_recv[0].tlast), .data_in_TSTRB(64'b0),
    .data_in_TVALID(axis_card_recv[0].tvalid && bench_busy), .data_in_TREADY(bench_input_ready),
    .data_out_TDATA(bench_result), .data_out_TKEEP(), .data_out_TLAST(), .data_out_TSTRB(),
    .data_out_TVALID(bench_result_valid), .data_out_TREADY(1'b1),
    .ap_clk(aclk), .ap_rst_n(aresetn)
);
assign bench_phase_word = 0;
assign bench_phase = 0;
end
if (BENCH_VARIANT != 6) begin
    assign pp_start=0; assign pp_end=0; assign cnn_start=0;
    assign logit=0; assign produced_tokens=0;
end
endgenerate
always_comb axis_host_recv[0].tie_off_s();
always_comb axis_host_send[0].tie_off_m();
always_comb axis_card_send[0].tie_off_m();
always_comb sq_wr.tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb notify.tie_off_m();

wire benchmark_debug_activity = axis_card_recv[0].tvalid && axis_card_recv[0].tready;
`include "debug_probe.svh"
