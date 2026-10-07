// Original no-ILA hello-world datapath plus the campaign's shared debug keepalive.
import lynxTypes::*;

perf_local inst_host_link (
    .axis_in(axis_host_recv[0]),
    .axis_out(axis_host_send[0]),
    .aclk(aclk),
    .aresetn(aresetn)
);

always_comb axis_host_recv[1].tie_off_s();
always_comb axis_host_send[1].tie_off_m();
always_comb notify.tie_off_m();
always_comb sq_rd.tie_off_m();
always_comb sq_wr.tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();
always_comb axi_ctrl.tie_off_s();

wire benchmark_debug_activity = axis_host_recv[0].tvalid && axis_host_recv[0].tready;
`include "debug_probe.svh"
