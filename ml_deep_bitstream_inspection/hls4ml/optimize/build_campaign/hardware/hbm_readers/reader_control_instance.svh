logic busy, start_frame;
logic [63:0] config_words [16];
logic [63:0] tick, active_setting;
logic [23:0] event_signals;
logic [63:0] transport_counters [16];
logic engine_ready, engine_done, engine_error;
logic result_valid;
logic [31:0] result_bits;

reader_control #(
    .ADDR_BITS($bits(axi_ctrl.awaddr)),
    .DATA_BITS($bits(axi_ctrl.wdata)),
    .VARIANT(`DEPLOY_VARIANT),
    // Even slots are first occurrences; odd slots are most recent occurrences.
    .LAST_EVENTS(24'haaaaaa)
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
    .events(event_signals), .counters(transport_counters),
    .engine_ready(engine_ready), .engine_done(engine_done), .engine_error(engine_error),
    .result_valid(result_valid), .result_bits(result_bits),
    .start(start_frame), .busy(busy), .config_words(config_words), .tick(tick), .active_setting(active_setting)
);
