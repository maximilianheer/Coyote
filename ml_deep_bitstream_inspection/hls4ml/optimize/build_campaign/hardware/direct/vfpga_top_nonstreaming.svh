import lynxTypes::*;
`include "direct_variant.svh"
logic busy;
logic [63:0] trial_id;
logic input_ready,pp_valid,pp_ready,cnn_valid,cnn_ready;
logic [15:0] pp_pixel,cnn_pixel;
logic [16:0] fifo_occupancy;
logic result_valid,result_record_valid;
logic [31:0] result_bits;
logic [63:0] result_trial;
logic [511:0] model_result;
logic rx_valid,tx_valid,tx_ready;
assign rx_valid=axis_host_recv[0].tvalid && busy;
assign axis_host_recv[0].tready=input_ready && busy;
assign tx_valid=axis_host_send[0].tvalid;
assign tx_ready=axis_host_send[0].tready;

direct_control #(.ADDR_BITS($bits(axi_ctrl.awaddr)),.DATA_BITS($bits(axi_ctrl.wdata)),.VARIANT(DIRECT_VARIANT),.FIFO_COUNT_BITS(17)) control (
    .clk(aclk),.rst_n(aresetn),
    .awaddr(axi_ctrl.awaddr),.araddr(axi_ctrl.araddr),
    .awvalid(axi_ctrl.awvalid),.wvalid(axi_ctrl.wvalid),.bready(axi_ctrl.bready),.arvalid(axi_ctrl.arvalid),.rready(axi_ctrl.rready),
    .wdata(axi_ctrl.wdata),.wstrb(axi_ctrl.wstrb),.awready(axi_ctrl.awready),.wready(axi_ctrl.wready),
    .bvalid(axi_ctrl.bvalid),.arready(axi_ctrl.arready),.rvalid(axi_ctrl.rvalid),.bresp(axi_ctrl.bresp),.rresp(axi_ctrl.rresp),.rdata(axi_ctrl.rdata),
    .in_valid(rx_valid),.in_ready(input_ready),.in_last(axis_host_recv[0].tlast),.in_data(axis_host_recv[0].tdata),.in_keep(axis_host_recv[0].tkeep),
    .out_valid(tx_valid),.out_ready(tx_ready),
    .pp_valid(pp_valid),.pp_ready(pp_ready),.cnn_valid(cnn_valid),.cnn_ready(cnn_ready),.fifo_occupancy(fifo_occupancy),
    .read_complete(cq_rd.valid && cq_rd.ready && cq_rd.data.dest==0),
    .write_complete(cq_wr.valid && cq_wr.ready && cq_wr.data.dest==0),
    .result_valid(result_valid),.result_bits(result_bits),.result_trial(result_trial),.result_record_valid(result_record_valid),
    .busy(busy),.trial_id(trial_id)
);
generate if(DIRECT_VARIANT==7) begin:checker_path
    preprocess_wrapper_hls_ip preprocess (
        .ap_clk(aclk),.ap_rst_n(aresetn),
        .data_in_TDATA(axis_host_recv[0].tdata),.data_in_TKEEP(axis_host_recv[0].tkeep),.data_in_TSTRB(axis_host_recv[0].tkeep),
        .data_in_TLAST(axis_host_recv[0].tlast),.data_in_TVALID(rx_valid),.data_in_TREADY(input_ready),
        .pixels_TDATA(pp_pixel),.pixels_TVALID(pp_valid),.pixels_TREADY(pp_ready)
    );
    frame_buffer #(.WIDTH(16),.DEPTH(65536)) pixel_fifo (
        .raw_complete(rx_valid && input_ready && axis_host_recv[0].tlast),
        .clk(aclk),.rst_n(aresetn),.in_data(pp_pixel),.in_valid(pp_valid),.in_ready(pp_ready),
        .out_data(cnn_pixel),.out_valid(cnn_valid),.out_ready(cnn_ready),.occupancy(fifo_occupancy)
    );
    cnn_wrapper_hls_ip cnn (
        .ap_clk(aclk),.ap_rst_n(aresetn),
        .pixels_TDATA(cnn_pixel),.pixels_TVALID(cnn_valid),.pixels_TREADY(cnn_ready),
        .data_out_TDATA(model_result),.data_out_TKEEP(),.data_out_TSTRB(),.data_out_TLAST(),
        .data_out_TVALID(result_valid),.data_out_TREADY(1'b1)
    );
    assign result_bits=model_result[31:0];assign result_trial=trial_id;assign result_record_valid=1;
    always_comb axis_host_send[0].tie_off_m();
    always_comb axis_host_recv[1].tie_off_s();
end else begin:transport
    assign pp_pixel=0;assign cnn_pixel=0;assign pp_valid=0;assign pp_ready=0;
    assign cnn_valid=0;assign cnn_ready=0;assign fifo_occupancy=0;assign model_result=0;
    if(DIRECT_VARIANT==9)begin:gpu
        localparam integer BRIDGE_BITS=577+$bits(axis_host_recv[0].tid);
        logic [BRIDGE_BITS-1:0] forwarded;
        logic [5:0] bridge_occupancy;
        elastic_fifo #(.WIDTH(BRIDGE_BITS),.DEPTH(32)) bridge_fifo (
            .clk(aclk),.rst_n(aresetn),
            .in_data({axis_host_recv[0].tid,axis_host_recv[0].tlast,axis_host_recv[0].tkeep,axis_host_recv[0].tdata}),
            .in_valid(rx_valid),.in_ready(input_ready),
            .out_data(forwarded),.out_valid(axis_host_send[0].tvalid),.out_ready(axis_host_send[0].tready),.occupancy(bridge_occupancy)
        );
        assign axis_host_send[0].tdata=forwarded[511:0];
        assign axis_host_send[0].tkeep=forwarded[575:512];
        assign axis_host_send[0].tlast=forwarded[576];
        assign axis_host_send[0].tid=forwarded[BRIDGE_BITS-1:577];
        assign axis_host_recv[1].tready=busy;
        assign result_valid=axis_host_recv[1].tvalid && busy;
        assign result_bits=axis_host_recv[1].tdata[31:0];
        assign result_trial=axis_host_recv[1].tdata[127:64];
        assign result_record_valid=axis_host_recv[1].tdata[63:32]==32'h43565233 &&
            axis_host_recv[1].tkeep==64'hffffffffffffffff && axis_host_recv[1].tlast;
    end else begin:sink
        assign input_ready=1;assign result_valid=0;assign result_bits=0;assign result_trial=0;assign result_record_valid=0;
        always_comb axis_host_send[0].tie_off_m();
        always_comb axis_host_recv[1].tie_off_s();
    end
end endgenerate
always_comb axis_host_send[1].tie_off_m();
always_comb sq_rd.tie_off_m();
always_comb sq_wr.tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb notify.tie_off_m();
wire benchmark_debug_activity=rx_valid && input_ready;
`include "debug_probe.svh"
