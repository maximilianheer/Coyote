import lynxTypes::*;
logic card_mode;
wire payload_valid = axis_rrsp_recv[0].tvalid;
wire payload_ready = axis_rrsp_recv[0].tready;

diagnostic_control #(
    .ADDR_BITS($bits(axi_ctrl.awaddr)),
    .DATA_BITS($bits(axi_ctrl.wdata))
) control (
    .clk(aclk), .rst_n(aresetn),
    .awaddr(axi_ctrl.awaddr), .araddr(axi_ctrl.araddr),
    .awvalid(axi_ctrl.awvalid), .wvalid(axi_ctrl.wvalid),
    .bready(axi_ctrl.bready), .arvalid(axi_ctrl.arvalid),
    .rready(axi_ctrl.rready), .wdata(axi_ctrl.wdata), .wstrb(axi_ctrl.wstrb),
    .awready(axi_ctrl.awready), .wready(axi_ctrl.wready),
    .bvalid(axi_ctrl.bvalid), .arready(axi_ctrl.arready),
    .rvalid(axi_ctrl.rvalid), .bresp(axi_ctrl.bresp),
    .rresp(axi_ctrl.rresp), .rdata(axi_ctrl.rdata),
    .request(sq_wr.valid && sq_wr.ready),
    .complete(cq_wr.valid && cq_wr.ready),
    .payload(payload_valid && payload_ready),
    .blocked(payload_valid && !payload_ready),
    .keep(axis_rrsp_recv[0].tkeep), .card_mode(card_mode)
);

// Native RDMA request metadata preserves context and completion semantics.
// Diagnostic mode uses either the ordinary host sink or its HBM equivalent.
always_comb begin
    sq_wr.data = rq_wr.data;
    sq_wr.data.strm = card_mode ? STRM_CARD : STRM_HOST;
    sq_wr.data.dest = 0;
    sq_wr.valid = rq_wr.valid;
    rq_wr.ready = sq_wr.ready;

    axis_card_send[0].tdata = axis_rrsp_recv[0].tdata;
    axis_card_send[0].tkeep = axis_rrsp_recv[0].tkeep;
    axis_card_send[0].tlast = axis_rrsp_recv[0].tlast;
    axis_card_send[0].tid = axis_rrsp_recv[0].tid;
    axis_card_send[0].tvalid = payload_valid && card_mode;

    axis_host_send[0].tdata = axis_rrsp_recv[0].tdata;
    axis_host_send[0].tkeep = axis_rrsp_recv[0].tkeep;
    axis_host_send[0].tlast = axis_rrsp_recv[0].tlast;
    axis_host_send[0].tid = axis_rrsp_recv[0].tid;
    axis_host_send[0].tvalid = payload_valid && !card_mode;
    axis_rrsp_recv[0].tready = card_mode
        ? axis_card_send[0].tready : axis_host_send[0].tready;
end

// No remote READ service in the WRITE-only diagnostic.
always_comb rq_rd.tie_off_s();
always_comb sq_rd.tie_off_m();
always_comb axis_rreq_send[0].tie_off_m();
always_comb axis_rrsp_send[0].tie_off_m();
always_comb axis_rreq_recv[0].tie_off_s();
always_comb axis_card_recv[0].tie_off_s();
always_comb axis_host_recv[0].tie_off_s();
always_comb axis_host_recv[1].tie_off_s();
always_comb axis_host_send[1].tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb notify.tie_off_m();
wire benchmark_debug_activity = payload_valid && payload_ready;
`include "debug_probe.svh"
