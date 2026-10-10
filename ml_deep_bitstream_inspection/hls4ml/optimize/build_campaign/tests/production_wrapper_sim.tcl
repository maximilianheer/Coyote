set work [pwd]
create_project wrapper_rtl "$work/sim_project" -part xcu55c-fsvh2892-2L-e -force
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]
cd "$work/core"
foreach script [glob -nocomplain *_ip.tcl] {source $script}
add_files [glob "$work/core/*.v"]
cd $work
add_files -fileset sim_1 "$work/production_wrapper_tb.sv"
if {[file exists "$work/production_passive_observer.svh"]} {
    add_files -fileset sim_1 "$work/passive_timestamps.sv"
    set_property include_dirs [list $work "$work/core"] [get_filesets sim_1]
    set_property verilog_define PASSIVE_FIFO_TAPS [get_filesets sim_1]
}
set_property top production_wrapper_tb [get_filesets sim_1]
set frame_count 8
if {[info exists ::env(PRODUCTION_RTL_FRAMES)]} {
    set frame_count $::env(PRODUCTION_RTL_FRAMES)
}
set driver_resets 0
if {[info exists ::env(DRIVER_RESETS)]} {set driver_resets $::env(DRIVER_RESETS)}
set_property generic "FRAME_COUNT=$frame_count DRIVER_RESETS=$driver_resets" [get_filesets sim_1]
set_property xsim.elaborate.debug_level typical [get_filesets sim_1]
set_property xsim.simulate.runtime all [get_filesets sim_1]
set simdir "$work/sim_project/wrapper_rtl.sim/sim_1/behav/xsim"
file mkdir $simdir
foreach file [glob -nocomplain "$work/core/*.dat"] {file copy -force $file $simdir}
file copy -force "$work/rtl_expected.txt" $simdir
launch_simulation -mode behavioral
close_sim
set f [open "$simdir/simulate.log" r];set output [read $f];close $f
if {[string first "PASS production wrapper frames=$frame_count" $output]<0} {error "Wrapper RTL check failed: $simdir/simulate.log"}
if {[file exists "$work/production_passive_observer.svh"] &&
    [regexp -all {PASS production passive frame=} $output]!=$frame_count} {
    error "Incomplete passive timestamp integration checks"
}
puts $output
close_project
exit
