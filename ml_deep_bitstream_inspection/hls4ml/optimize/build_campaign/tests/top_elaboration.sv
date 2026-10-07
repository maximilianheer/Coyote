// Elaboration-only harness: actual Coyote interfaces, maintained top include,
// and an HLS port stub. This checks wiring, not the synthesized CNN behavior.
module top_elaboration;
    import lynxTypes::*;
    logic aclk=0, aresetn=0;
    AXI4L axi_ctrl();
    AXI4S axis_host_recv[1]();
    AXI4S axis_host_send[1]();
    AXI4S axis_card_recv[1]();
    AXI4S axis_card_send[1]();
    metaIntf #(.STYPE(req_t)) sq_rd(.*), sq_wr(.*);
    metaIntf #(.STYPE(ack_t)) cq_rd(.*), cq_wr(.*);
    metaIntf #(.STYPE(irq_not_t)) notify(.*);
    `include "vfpga_top.svh"
endmodule

// Elaboration-only stub for the real ILA IP created by hardware/init_ip.tcl.
module ila_benchmark_keepalive(input logic clk, input logic [0:0] probe0);
endmodule

module model_wrapper_hls_ip (
    input logic ap_clk, ap_rst_n,
    input logic [511:0] data_in_TDATA,
    input logic [63:0] data_in_TKEEP, data_in_TSTRB,
    input logic data_in_TLAST, data_in_TVALID,
    output logic data_in_TREADY,
    output logic [511:0] data_out_TDATA,
    output logic [63:0] data_out_TKEEP, data_out_TSTRB,
    output logic data_out_TLAST, data_out_TVALID,
    input logic data_out_TREADY
`ifdef BENCH_STREAMING
    , output logic [31:0] pp_start, pp_end, cnn_start, logit, produced_tokens
`elsif BENCH_PHASE
    , output logic [31:0] phase
`endif
);
endmodule
