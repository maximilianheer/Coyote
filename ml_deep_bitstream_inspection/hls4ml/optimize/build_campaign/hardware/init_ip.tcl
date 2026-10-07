# Coyote's user debug bridge requires a connected debug core (Chipscope 16-320).
# Match this IP configuration across hello-world and every diagnostic variant.
create_ip -name ila -vendor xilinx.com -library ip -version 6.2 -module_name ila_benchmark_keepalive
set_property -dict [list CONFIG.C_NUM_OF_PROBES {1} CONFIG.C_PROBE0_WIDTH {1} CONFIG.C_DATA_DEPTH {1024}] [get_ips ila_benchmark_keepalive]
