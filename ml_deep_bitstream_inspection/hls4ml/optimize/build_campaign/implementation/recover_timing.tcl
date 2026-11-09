# Same netlist/clock constraints; each invocation writes to its own attempt.
if {[catch {
    lassign $argv original_base output seed strategy reference boundary_cell boundary_loc
    source $original_base
    set_param general.maxThreads 8
    set dcp_dir "$output/checkpoints"
    set rprt_dir "$output/reports"
    file mkdir $dcp_dir $rprt_dir
    open_checkpoint $seed
    if {$strategy eq "boundary_relocation"} {
        # Placement guidance only; reuse this attempt's own optimized netlist.
        # The completed sink supplies a location, never an IP or checkpoint seed.
        set target [get_cells -hier -filter [format {NAME == "%s"} $boundary_cell]]
        if {[llength $target] != 1} {error "Expected one shell boundary register"}
        set_property LOC $boundary_loc $target
        puts [list BOUNDARY_PLACEMENT [get_property NAME $target] LOC [get_property LOC $target]]
        place_design -directive Explore
        phys_opt_design -directive AggressiveFanoutOpt
        route_design -directive NoTimingRelaxation
        phys_opt_design -directive AggressiveExplore
    } elseif {$strategy == 6} {
        # The launching word-counter FF has low fanout. The measured 512-load
        # net is driven by a later LUT that gates the wide read-data registers.
        # Select that data-control cone, excluding clock/reset infrastructure.
        set nets [get_nets -hier -filter {NAME =~ inst_shell/inst_int_hbm/path_*/axi_dwidth_converter_0/* && NAME =~ *USE_READ.* && NAME =~ *S_AXI_RDATA_II*}]
        set targets {}
        set evidence [open "$rprt_dir/hbm_read_control_replication.txt" w]
        foreach net [lsort -unique $nets] {
            set drivers [get_cells -of_objects [get_pins -leaf -of_objects $net -filter {DIRECTION == OUT}]]
            if {[llength $drivers] != 1} {continue}
            set ref [get_property REF_NAME [lindex $drivers 0]]
            if {![string match {FD*} $ref] && ![string match {LUT*} $ref]} {continue}
            set loads [get_pins -leaf -of_objects $net -filter {DIRECTION == IN}]
            if {[llength $loads] >= 64} {
                lappend targets $net
                puts $evidence [list $net fanout [llength $loads]]
            }
        }
        close $evidence
        if {[llength $targets] == 0} {error "Measured HBM read control nets missing"}
        phys_opt_design -force_replication_on_nets $targets
        route_design -directive NoTimingRelaxation
        phys_opt_design -directive AggressiveExplore
    } elseif {$strategy == 5} {
        # Target the measured wide-bus control paths explicitly. Automatic
        # fanout optimization can leave critical register-slice drivers alone.
        set state_cells [get_cells -hier -filter {NAME =~ inst_shell/* && NAME =~ *state_reg* && REF_NAME =~ FD*}]
        set candidates [get_nets -of_objects [get_pins -of_objects $state_cells -filter {REF_PIN_NAME == Q}]]
        set candidates [concat $candidates [get_nets -hier -regexp {inst_shell/inst_int_hbm/path_[0-9]+/slice_1/inst/w\.w_pipe/.*}]]
        set selected {}
        set evidence [open "$rprt_dir/forced_replication_nets.txt" w]
        foreach net [lsort -unique $candidates] {
            # Never request replication of clock/reset infrastructure. The HBM
            # hierarchy also contains aclk, driven by a clock buffer/MMCM.
            set driver_pins [get_pins -leaf -of_objects $net -filter {DIRECTION == OUT}]
            set driver_cells [get_cells -of_objects $driver_pins]
            if {[llength $driver_cells] != 1} {continue}
            set ref [get_property REF_NAME [lindex $driver_cells 0]]
            if {![string match {FD*} $ref] && ![string match {LUT*} $ref]} {continue}
            set loads [get_pins -leaf -of_objects $net -filter {DIRECTION == IN}]
            if {[llength $loads] >= 64} {
                lappend selected $net
                puts $evidence [list $net fanout [llength $loads]]
            }
        }
        close $evidence
        if {[llength $selected] == 0} {error "No measured high-fanout driver candidates found"}
        phys_opt_design -force_replication_on_nets $selected
        route_design -directive NoTimingRelaxation
        phys_opt_design -directive AggressiveExplore
    } elseif {$strategy == 1} {
        phys_opt_design -directive AggressiveFanoutOpt
        route_design -directive NoTimingRelaxation
        phys_opt_design -directive Explore
    } elseif {$strategy == 2} {
        phys_opt_design -directive AggressiveFanoutOpt
        route_design -directive MoreGlobalIterations
        phys_opt_design -directive AggressiveExplore
    } elseif {$strategy == 3} {
        place_design -directive Explore
        phys_opt_design -directive AlternateReplication
        route_design -directive NoTimingRelaxation
        phys_opt_design -directive AggressiveExplore
    } elseif {$strategy == 4} {
        # Physical guidance only: the current netlist remains the seed design.
        # Preserve the DFX floorplan/boundary pins and target nonnegative slack.
        read_checkpoint -incremental -directive TimingClosure $reference
        report_incremental_reuse -file "$rprt_dir/incremental_reuse.rpt"
        place_design
        phys_opt_design
        route_design
        phys_opt_design -directive Explore
    } else {error "Unknown recovery strategy $strategy"}
    write_checkpoint "$dcp_dir/shell_routed.dcp"
    report_timing_summary -file "$rprt_dir/shell_timing_summary.rpt"
    report_route_status -file "$rprt_dir/shell_route_status.rpt"
    report_utilization -file "$rprt_dir/shell_utilization.rpt"
    report_utilization -hierarchical -file "$rprt_dir/shell_utilization_hierarchical.rpt"
    report_drc -ruledeck bitstream_checks -file "$rprt_dir/shell_drc_bitstream_checks.rpt"
    close_design
} message]} {puts stderr $message; exit 1}
exit 0
