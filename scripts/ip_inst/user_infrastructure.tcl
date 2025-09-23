create_ip -name debug_bridge -vendor xilinx.com -library ip -version 3.0 -module_name debug_bridge_user
set_property -dict [list CONFIG.C_DEBUG_MODE {1} CONFIG.C_NUM_BS_MASTER {0} CONFIG.C_DESIGN_TYPE {1}] [get_ips debug_bridge_user]

create_ip -name ila -vendor xilinx.com -library ip -version 6.2 -module_name ila_host_networking
set_property -dict [list CONFIG.C_PROBE3_WIDTH {512} CONFIG.C_PROBE4_WIDTH {64} CONFIG.C_PROBE8_WIDTH {512} CONFIG.C_PROBE9_WIDTH {64} CONFIG.C_NUM_OF_PROBES {10} CONFIG.C_EN_STRG_QUAL {1} CONFIG.ALL_PROBE_SAME_MU_CNT {2} CONFIG.C_DATA_DEPTH {8192}] [get_ips ila_host_networking]
