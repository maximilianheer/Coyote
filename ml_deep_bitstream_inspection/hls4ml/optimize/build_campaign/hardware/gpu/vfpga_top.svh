import lynxTypes::*;
`include "direct_variant.svh"
logic busy,input_ready,result_valid,result_record_valid;
logic [63:0] trial_id,result_trial,tick,ready_addr,payload_addr,timeout_ticks;
logic [31:0] result_bits,poll_gap;
logic [5:0] poll_context;
logic poll_active,poll_fatal,forwarded_done;
logic [63:0] poll_stats[9];
wire rx_valid=axis_host_recv[0].tvalid && busy;
assign axis_host_recv[0].tready=input_ready && busy;
gpu_control #(.ADDR_BITS($bits(axi_ctrl.awaddr)),.DATA_BITS($bits(axi_ctrl.wdata)),.VARIANT(DIRECT_VARIANT)) control (
 .clk(aclk),.rst_n(aresetn),
 .awaddr(axi_ctrl.awaddr),.araddr(axi_ctrl.araddr),.awvalid(axi_ctrl.awvalid),.wvalid(axi_ctrl.wvalid),
 .bready(axi_ctrl.bready),.arvalid(axi_ctrl.arvalid),.rready(axi_ctrl.rready),.wdata(axi_ctrl.wdata),.wstrb(axi_ctrl.wstrb),
 .awready(axi_ctrl.awready),.wready(axi_ctrl.wready),.bvalid(axi_ctrl.bvalid),.arready(axi_ctrl.arready),
 .rvalid(axi_ctrl.rvalid),.bresp(axi_ctrl.bresp),.rresp(axi_ctrl.rresp),.rdata(axi_ctrl.rdata),
 .in_valid(rx_valid),.in_ready(input_ready),.in_last(axis_host_recv[0].tlast),.in_data(axis_host_recv[0].tdata),.in_keep(axis_host_recv[0].tkeep),
 .out_valid(axis_host_send[0].tvalid),.out_ready(axis_host_send[0].tready),
 .pp_valid(1'b0),.pp_ready(1'b0),.cnn_valid(1'b0),.cnn_ready(1'b0),.fifo_occupancy(6'b0),
 .read_complete(cq_rd.valid && cq_rd.ready && cq_rd.data.dest==0 && cq_rd.data.host),
 .write_complete(cq_wr.valid && cq_wr.ready && cq_wr.data.dest==0 && cq_wr.data.host),
 .result_valid(result_valid),.result_bits(result_bits),.result_trial(result_trial),.result_record_valid(result_record_valid),
 .busy(busy),.trial_id(trial_id),.poll_active(poll_active),.poll_fatal(poll_fatal),.poll_stats(poll_stats),
 .ready_addr(ready_addr),.payload_addr(payload_addr),.timeout_ticks(timeout_ticks),.poll_gap(poll_gap),
 .poll_context(poll_context),.current_tick(tick),.forwarded_done(forwarded_done)
);
generate if(DIRECT_VARIANT==11)begin:p2p
 localparam integer BRIDGE_BITS=577+$bits(axis_host_recv[0].tid);
 logic [BRIDGE_BITS-1:0] forwarded;
 logic [5:0] occupancy;
 elastic_fifo #(.WIDTH(BRIDGE_BITS),.DEPTH(32)) bridge_fifo (
  .clk(aclk),.rst_n(aresetn),.in_data({axis_host_recv[0].tid,axis_host_recv[0].tlast,axis_host_recv[0].tkeep,axis_host_recv[0].tdata}),
  .in_valid(rx_valid),.in_ready(input_ready),.out_data(forwarded),.out_valid(axis_host_send[0].tvalid),
  .out_ready(axis_host_send[0].tready),.occupancy(occupancy));
 assign axis_host_send[0].tdata=forwarded[511:0];
 assign axis_host_send[0].tkeep=forwarded[575:512];
 assign axis_host_send[0].tlast=forwarded[576];
 assign axis_host_send[0].tid=forwarded[BRIDGE_BITS-1:577];
 logic req_valid,rsp_ready;
 logic [63:0] req_addr;
 gpu_poll poller(
  .clk(aclk),.rst_n(aresetn),.busy(busy),.input_done(forwarded_done),.tick(tick),
  .ready_addr(ready_addr),.payload_addr(payload_addr),.trial(trial_id),.gap_cycles(poll_gap),
  .req_valid(req_valid),.req_ready(sq_rd.ready),.req_addr(req_addr),
  .rsp_valid(axis_host_recv[1].tvalid),.rsp_ready(rsp_ready),.rsp_data(axis_host_recv[1].tdata),
  .rsp_wellformed(axis_host_recv[1].tkeep==64'hffffffffffffffff && axis_host_recv[1].tlast && axis_host_recv[1].tid==poll_context),
  .ack(cq_rd.valid && cq_rd.ready && !cq_rd.data.host && cq_rd.data.dest==1 && cq_rd.data.pid==poll_context),
  .active(poll_active),.fatal(poll_fatal),.result_valid(result_valid),.result_bits(result_bits),.result_trial(result_trial),.stats(poll_stats));
 assign axis_host_recv[1].tready=rsp_ready;
 assign result_record_valid=1;
 always_comb begin
  sq_rd.data='0;sq_rd.valid=req_valid;
  sq_rd.data.last=1;sq_rd.data.pid=poll_context;sq_rd.data.len=64;
  sq_rd.data.vaddr=req_addr;sq_rd.data.strm=STRM_HOST;sq_rd.data.opcode=LOCAL_READ;sq_rd.data.dest=1;
 end
end else begin:host_path
 assign input_ready=1;
 always_comb axis_host_send[0].tie_off_m();
 always_comb sq_rd.tie_off_m();
 assign axis_host_recv[1].tready=busy;
 assign result_valid=axis_host_recv[1].tvalid && busy;
 assign result_bits=axis_host_recv[1].tdata[31:0];
 assign result_trial=axis_host_recv[1].tdata[127:64];
 assign result_record_valid=axis_host_recv[1].tdata[63:32]==32'h43565234 && axis_host_recv[1].tkeep==64'hffffffffffffffff && axis_host_recv[1].tlast;
 assign poll_active=0;assign poll_fatal=0;
 for(genvar i=0;i<9;i++)assign poll_stats[i]=0;
end endgenerate
always_comb axis_host_send[1].tie_off_m();
always_comb sq_wr.tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb notify.tie_off_m();
wire benchmark_debug_activity=rx_valid && input_ready;
`include "debug_probe.svh"
