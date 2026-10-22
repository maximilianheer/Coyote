# Tool-only workaround for the Vitis 2024.2 graphical co-simulation stall.
# Keep generated RTL, native dataflow monitors, input vectors and depth selection.
proc iteration_fifo_batch_setup {project_name} {
    set directory "${project_name}_prj/solution1/sim/verilog"
    set script "$directory/run_xsim.sh"
    set handle [open $script r];set original [read $handle];close $handle
    set output {}
    set replaced 0
    foreach line [split $original "\n"] {
        if {[regexp {^(/[^ ]*/bin/xsim) } $line -> executable]} {
            lappend output "$executable --noieeewarnings $project_name -tclbatch ${project_name}.tcl"
            incr replaced
        } else {lappend output $line}
    }
    if {$replaced != 1} {error "Cannot identify the unique native xsim invocation"}
    file copy -force $script "$script.native"
    set handle [open $script w];puts $handle [join $output "\n"];close $handle
    set script "$directory/${project_name}.tcl"
    file copy -force $script "$script.native"
    set handle [open $script w]
    puts $handle {
        set completed 0
        set expected [get_value -radix unsigned /apatb_iteration_model_top/AUTOTB_TRANSACTION_NUM]
        # Bounded Tcl runs service the simulator connection and expose progress.
        for {set chunk 0} {$chunk < 500} {incr chunk} {
            run 100 us
            set completed [get_value -radix unsigned /apatb_iteration_model_top/done_cnt]
            puts "PROFILE_PROGRESS time=[current_time] completed=$completed/$expected"
            flush stdout
            if {$completed == $expected} {break}
        }
        if {$completed != $expected} {error "FIFO profiling failed to complete within the simulation watchdog"}
        quit
    }
    close $handle
}
