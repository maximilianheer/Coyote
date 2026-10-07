# Invoke in a directory containing the unchanged synthesized HLS Verilog/dat/Tcl
# files and the maintained testbench. Vivado resolves the real floating-point IP
# simulation libraries; no behavioral replacements for production arithmetic.
set work [pwd]
create_project rtl_check "$work/sim_project" -part xcu55c-fsvh2892-2L-e -force
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]
foreach script [glob "$work/*_ip.tcl"] { source $script }
add_files [glob "$work/*.v"]
add_files -fileset sim_1 "$work/streaming_rtl_tb.sv"
set_property top streaming_rtl_tb [get_filesets sim_1]
set_property xsim.elaborate.debug_level typical [get_filesets sim_1]
set_property xsim.simulate.custom_tcl "$work/streaming_wave.tcl" [get_filesets sim_1]
set simdir "$work/sim_project/rtl_check.sim/sim_1/behav/xsim"
file mkdir $simdir
foreach path [glob -nocomplain "$work/*.dat" "$work/rtl_expected.txt"] {
    file copy -force $path $simdir
}
launch_simulation -mode behavioral
close_sim
set f [open "$simdir/simulate.log" r]
set output [read $f]
close $f
if {[string first "PASS synthesized streaming RTL" $output] < 0} {
    error "Synthesized streaming RTL failed; inspect $simdir/simulate.log"
}
puts $output
close_project
exit
