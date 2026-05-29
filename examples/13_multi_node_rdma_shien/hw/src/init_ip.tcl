create_ip -name ila -vendor xilinx.com -library ip -version 6.2 -module_name ila_perf_rdma
set_property -dict [list CONFIG.C_NUM_OF_PROBES {20} CONFIG.C_EN_STRG_QUAL {1} CONFIG.ALL_PROBE_SAME_MU_CNT {2} \
    CONFIG.C_PROBE17_WIDTH {24} \
    CONFIG.C_PROBE18_WIDTH {48} \
    CONFIG.C_PROBE19_WIDTH {48}] [get_ips ila_perf_rdma]
