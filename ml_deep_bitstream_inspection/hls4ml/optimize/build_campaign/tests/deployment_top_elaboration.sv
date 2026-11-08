// Wiring harness uses real generated Coyote types and interfaces. HLS port
// stubs only check integration; pixel semantics are checked by C-simulation.
module top_elaboration;
    import lynxTypes::*;
    logic aclk = 0, aresetn = 0;
    AXI4L axi_ctrl();
    AXI4SR axis_host_recv[2]();
    AXI4SR axis_host_send[2]();
    AXI4SR axis_card_recv[1]();
    AXI4SR axis_card_send[1]();
    AXI4SR axis_rreq_recv[1]();
    AXI4SR axis_rreq_send[1]();
    AXI4SR axis_rrsp_recv[1]();
    AXI4SR axis_rrsp_send[1]();
    metaIntf #(.STYPE(req_t)) sq_rd(.*), sq_wr(.*), rq_rd(.*), rq_wr(.*);
    metaIntf #(.STYPE(ack_t)) cq_rd(.*), cq_wr(.*);
    metaIntf #(.STYPE(irq_not_t)) notify(.*);
    `include "vfpga_top.svh"
endmodule

module ila_benchmark_keepalive(input logic clk, input logic [0:0] probe0);
endmodule

module cnn_wrapper_hls_ip (
    input logic ap_clk, ap_rst_n,
    input logic [15:0] pixels_TDATA,
    input logic pixels_TVALID,
    output logic pixels_TREADY,
    output logic [511:0] data_out_TDATA,
    output logic [63:0] data_out_TKEEP, data_out_TSTRB,
    output logic data_out_TLAST, data_out_TVALID,
    input logic data_out_TREADY
);
endmodule

module hbm_gather_hls_ip (
    input logic ap_clk, ap_rst_n,
    input logic [127:0] frame_TDATA,
    input logic frame_TVALID,
    output logic frame_TREADY,
    output logic [63:0] addresses_TDATA,
    output logic addresses_TVALID,
    input logic addresses_TREADY,
    input logic [511:0] words_TDATA,
    input logic words_TVALID,
    output logic words_TREADY,
    output logic [15:0] pixels_TDATA,
    output logic pixels_TVALID,
    input logic pixels_TREADY
);
endmodule

module network_preprocess_hls_ip (
    input logic ap_clk, ap_rst_n,
    input logic [63:0] lengths_TDATA,
    input logic lengths_TVALID,
    output logic lengths_TREADY,
    input logic [511:0] raw_TDATA,
    input logic [63:0] raw_TKEEP, raw_TSTRB,
    input logic raw_TLAST, raw_TVALID,
    output logic raw_TREADY,
    output logic [15:0] pixels_TDATA,
    output logic pixels_TVALID,
    input logic pixels_TREADY
);
endmodule
