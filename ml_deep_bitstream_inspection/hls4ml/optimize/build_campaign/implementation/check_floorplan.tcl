# Read-only input check: all newly written checkpoints remain in the output dir.
if {[catch {
    lassign $argv seed refinement output
    set_param general.maxThreads 8
    open_checkpoint $seed
    source $refinement
    set expected_slices [llength $after_slices]
    set expected_resources $after_resources
    write_checkpoint "$output/refined_linked.dcp"
    close_design
    open_checkpoint "$output/refined_linked.dcp"
    set pb [get_pblocks pblock_inst_user_wrapper_0]
    set restored_slices [get_sites -of_objects $pb -filter {NAME =~ SLICE*}]
    set restored_resources [lsort [get_sites -of_objects $pb -filter $resource_filter]]
    if {[llength $restored_slices] != $expected_slices || $restored_resources ne $expected_resources} {
        error "Refined floorplan did not survive checkpoint reopening"
    }
    puts "FLOORPLAN_REOPEN_PASS slices=$expected_slices retained_resources=[llength $restored_resources]"
    close_design
} message]} {puts stderr $message; exit 1}
exit 0
