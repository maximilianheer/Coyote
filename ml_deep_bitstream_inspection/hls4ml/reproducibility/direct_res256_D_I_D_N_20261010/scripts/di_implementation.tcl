# Successful D_I route_01 recipe, applied to a fresh linked netlist.
if {[catch {
source {@BASE@}
set_param general.maxThreads 8
open_checkpoint "$dcp_dir/shell_linked.dcp"
opt_design -directive Explore
write_checkpoint -force "$dcp_dir/shell_opted.dcp"
set target [get_cells -hier -filter {NAME == "inst_shell/inst_shell_data_cc/genblk1[1].inst_s0_axis_dyn_in/genblk1[2].inst_reg/inst_reg_slice/inst/axisc_register_slice_0/state_reg[0]"}]
if {[llength $target] != 1} {error "Expected one shell boundary register"}
set_property LOC SLICE_X166Y196 $target
place_design -directive Explore
phys_opt_design -directive AggressiveFanoutOpt
route_design -directive NoTimingRelaxation
phys_opt_design -directive AggressiveExplore
write_checkpoint -force "$dcp_dir/shell_routed.dcp"
report_timing_summary -file "$rprt_dir/shell_timing_summary.rpt"
report_route_status -file "$rprt_dir/shell_route_status.rpt"
report_utilization -file "$rprt_dir/shell_utilization.rpt"
report_utilization -hierarchical -file "$rprt_dir/shell_utilization_hierarchical.rpt"
report_drc -ruledeck bitstream_checks -file "$rprt_dir/shell_drc_bitstream_checks.rpt"
close_design
} message]} {puts stderr $message; exit 1}
exit 0
