# Same netlist/clock constraints; each invocation writes to its own attempt.
if {[catch {
    lassign $argv original_base output seed strategy reference
    source $original_base
    set_param general.maxThreads 8
    set dcp_dir "$output/checkpoints"
    set rprt_dir "$output/reports"
    file mkdir $dcp_dir $rprt_dir
    open_checkpoint $seed
    if {$strategy == 1} {
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
