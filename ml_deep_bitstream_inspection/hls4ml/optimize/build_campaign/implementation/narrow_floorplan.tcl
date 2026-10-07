# Executed as ordinary Tcl after link_design, never loaded as an XDC file.
set pb [get_pblocks pblock_inst_user_wrapper_0]
if {[llength $pb] != 1} {error "Expected one user pblock for refinement"}
set before_slices [get_sites -of_objects $pb -filter {NAME =~ SLICE*}]
set original_ranges [get_property GRID_RANGES $pb]
# Keep every original BRAM site. DSP/URAM columns are also retained if the user
# design uses those primitive types; unused columns need not reserve PR area.
set resource_filter {NAME =~ RAMB*}
set used_dsp [get_cells -quiet -hier -filter {NAME =~ inst_shell/inst_dynamic/inst_user_wrapper_0/* && REF_NAME =~ DSP*}]
set used_uram [get_cells -quiet -hier -filter {NAME =~ inst_shell/inst_dynamic/inst_user_wrapper_0/* && REF_NAME =~ URAM*}]
if {[llength $used_dsp]} {append resource_filter { || NAME =~ DSP*}}
if {[llength $used_uram]} {append resource_filter { || NAME =~ URAM*}}
set before_resources [lsort [get_sites -of_objects $pb -filter $resource_filter]]
puts "FLOORPLAN_RESOURCE_USAGE dsp_cells=[llength $used_dsp] uram_cells=[llength $used_uram] retained_sites=[llength $before_resources]"
set xs {}
set ys {}
foreach site $before_slices {
    if {[regexp {SLICE_X([0-9]+)Y([0-9]+)} $site -> x y]} {
        lappend xs $x
        lappend ys $y
    }
}
set xs [lsort -integer -unique $xs]
set ys [lsort -integer -unique $ys]
if {[llength $xs] < 2 || [llength $ys] < 1} {error "No slice columns available for narrowing"}
proc refine_span {pb original_ranges xs ys first last} {
    resize_pblock $pb -add $original_ranges
    if {$first > 0} {
        resize_pblock $pb -remove [format {SLICE_X%dY%d:SLICE_X%dY%d} [lindex $xs 0] [lindex $ys 0] [lindex $xs [expr {$first-1}]] [lindex $ys end]]
    }
    if {$last < [llength $xs]-1} {
        resize_pblock $pb -remove [format {SLICE_X%dY%d:SLICE_X%dY%d} [lindex $xs [expr {$last+1}]] [lindex $ys 0] [lindex $xs end] [lindex $ys end]]
    }
}
# Try half-width first, then widen until snapping retains the required sites.
# Trim the left edge first, then the right; inspect effective DERIVED_RANGES.
set last [expr {[llength $xs]-1}]
for {set first [expr {[llength $xs]/2}]} {$first >= 0} {incr first -1} {
    refine_span $pb $original_ranges $xs $ys $first $last
    if {[lsort [get_sites -of_objects $pb -filter $resource_filter]] eq $before_resources} {break}
}
if {$first < 0} {error "Cannot restore original resource sites while trimming left edge"}
set midpoint [expr {$first+([llength $xs]-$first)/2-1}]
for {set last $midpoint} {$last < [llength $xs]} {incr last} {
    refine_span $pb $original_ranges $xs $ys $first $last
    if {[lsort [get_sites -of_objects $pb -filter $resource_filter]] eq $before_resources} {break}
}
if {$last >= [llength $xs]} {error "Cannot restore original resource sites while trimming right edge"}
set after_slices [get_sites -of_objects $pb -filter {NAME =~ SLICE*}]
set after_resources [lsort [get_sites -of_objects $pb -filter $resource_filter]]
puts "FLOORPLAN_REFINEMENT_COUNTS slices_before=[llength $before_slices] slices_after=[llength $after_slices] resources_before=[llength $before_resources] resources_after=[llength $after_resources]"
puts "FLOORPLAN_GRID_RANGES [get_property GRID_RANGES $pb]"
puts "FLOORPLAN_DERIVED_RANGES [get_property DERIVED_RANGES $pb]"
if {[llength $after_slices] == 0 || [llength $after_slices] >= [llength $before_slices]} {
    error "Requested narrowing did not reduce the effective slice-site count"
}
if {$before_resources ne $after_resources} {error "Narrowing changed BRAM/DSP/URAM sites"}
puts "FLOORPLAN_REFINEMENT_APPLIED slices_before=[llength $before_slices] slices_after=[llength $after_slices] retained_resources=[llength $after_resources]"
