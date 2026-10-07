// Keep Coyote's mandatory user debug bridge clocked even without application ILAs.
// Identical one-bit, 1024-sample ILA in every campaign design; report its cost.
ila_benchmark_keepalive inst_ila_benchmark_keepalive (
    .clk(aclk),
    .probe0(benchmark_debug_activity)
);
