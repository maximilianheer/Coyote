// Single production HLS IP; original host input and result DMA connections.
wire observer_pixel_write, observer_pixel_read;
model_wrapper_hls_ip inst_model(
    .data_in_TDATA(axis_host_recv[0].tdata),
    .data_in_TKEEP(axis_host_recv[0].tkeep),
    .data_in_TLAST(axis_host_recv[0].tlast),
    .data_in_TSTRB(0),
    .data_in_TVALID(axis_host_recv[0].tvalid),
    .data_in_TREADY(axis_host_recv[0].tready),
    .data_out_TDATA(axis_host_send[0].tdata),
    .data_out_TKEEP(axis_host_send[0].tkeep),
    .data_out_TLAST(axis_host_send[0].tlast),
    .data_out_TSTRB(),
    .data_out_TVALID(axis_host_send[0].tvalid),
    .data_out_TREADY(axis_host_send[0].tready),
    .observer_pixel_write(observer_pixel_write),
    .observer_pixel_read(observer_pixel_read),
    .ap_clk(aclk), .ap_rst_n(aresetn)
);

// Read-only observer: no monitor output connects to the data path.
passive_timestamps #(
    .ADDR_BITS($bits(axi_ctrl.awaddr)), .DATA_BITS($bits(axi_ctrl.wdata))
) observer (
    .clk(aclk), .rst_n(aresetn),
    .awaddr(axi_ctrl.awaddr), .araddr(axi_ctrl.araddr),
    .awvalid(axi_ctrl.awvalid), .wvalid(axi_ctrl.wvalid),
    .bready(axi_ctrl.bready), .arvalid(axi_ctrl.arvalid), .rready(axi_ctrl.rready),
    .wdata(axi_ctrl.wdata), .wstrb(axi_ctrl.wstrb),
    .awready(axi_ctrl.awready), .wready(axi_ctrl.wready),
    .bvalid(axi_ctrl.bvalid), .arready(axi_ctrl.arready), .rvalid(axi_ctrl.rvalid),
    .bresp(axi_ctrl.bresp), .rresp(axi_ctrl.rresp), .rdata(axi_ctrl.rdata),
    .in_valid(axis_host_recv[0].tvalid), .in_ready(axis_host_recv[0].tready),
    .in_length(axis_host_recv[0].tdata[63:0]),
    .pixel_write(observer_pixel_write), .pixel_read(observer_pixel_read),
    .out_valid(axis_host_send[0].tvalid), .out_ready(axis_host_send[0].tready)
);

always_comb sq_rd.tie_off_m();
always_comb sq_wr.tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb notify.tie_off_m();
wire benchmark_debug_activity = axis_host_recv[0].tvalid && axis_host_recv[0].tready;
`include "debug_probe.svh"
