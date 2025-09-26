create_ip -name debug_bridge -vendor xilinx.com -library ip -version 3.0 -module_name debug_bridge_user
set_property -dict [list CONFIG.C_DEBUG_MODE {1} CONFIG.C_NUM_BS_MASTER {0} CONFIG.C_DESIGN_TYPE {1}] [get_ips debug_bridge_user]

create_ip -name ila -vendor xilinx.com -library ip -version 6.2 -module_name ila_req_trace
set_property -dict [list CONFIG.C_PROBE2_WIDTH {128} CONFIG.C_NUM_OF_PROBES {3} CONFIG.C_EN_STRG_QUAL {1} CONFIG.ALL_PROBE_SAME_MU_CNT {2} CONFIG.C_DATA_DEPTH {1024}] [get_ips ila_req_trace]
