set work [pwd]
create_project direct_rtl "$work/sim_project" -part xcu55c-fsvh2892-2L-e -force
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]
foreach dir {pp cnn} {
    cd "$work/$dir"
    foreach script [glob -nocomplain *_ip.tcl] {source $script}
    add_files [glob "$work/$dir/*.v"]
}
cd $work
add_files "$work/elastic_fifo.sv"
add_files "$work/direct_control.sv"
add_files -fileset sim_1 "$work/direct_pipe_tb.sv"
set_property top direct_pipe_tb [get_filesets sim_1]
if {[info exists ::env(DIRECT_STARTUP_IDLE)]} {
    set parameters "STARTUP_IDLE=$::env(DIRECT_STARTUP_IDLE) ALWAYS_READY=$::env(DIRECT_ALWAYS_READY)"
    if {[info exists ::env(DIRECT_INTERFRAME_IDLE)]} {append parameters " INTERFRAME_IDLE=$::env(DIRECT_INTERFRAME_IDLE)"}
    set_property generic $parameters [get_filesets sim_1]
}
set_property xsim.elaborate.debug_level typical [get_filesets sim_1]
set_property xsim.simulate.runtime all [get_filesets sim_1]
set simdir "$work/sim_project/direct_rtl.sim/sim_1/behav/xsim"
file mkdir $simdir
foreach dir {pp cnn} {
    foreach file [glob -nocomplain "$work/$dir/*.dat"] {file copy -force $file $simdir}
}
file copy -force "$work/direct_expected.txt" $simdir
launch_simulation -mode behavioral
close_sim
set f [open "$simdir/simulate.log" r];set output [read $f];close $f
if {[string first "PASS direct synthesized RTL" $output]<0} {error "Direct RTL check failed: $simdir/simulate.log"}
file copy -force "$simdir/cycles.csv" "$work/cycles.csv"
puts $output
close_project
exit
