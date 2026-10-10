# Inspect physical optimizations across the checker/shell boundary.
if {$argc != 2} {error "usage: export_routed_boundary.tcl CHECKPOINT OUTPUT_DIR"}
set output [file normalize [lindex $argv 1]]
file mkdir $output
open_checkpoint [lindex $argv 0]
set cnn [get_cells -hier -filter {REF_NAME == cnn_wrapper_hls_ip}]
if {[llength $cnn] != 1} {error "expected one CNN"}
set app [get_cells [file dirname [get_property NAME $cnn]]]
set wrapper [get_cells [file dirname [get_property NAME $app]]]
write_verilog -force -mode funcsim -cell $wrapper "$output/wrapper_routed.v"
set f [open "$output/boundary_cones.txt" w]
proc trace_pin {pin depth} {
    global f seen
    set nets [get_nets -segments -of_objects $pin]
    set drivers [get_pins -leaf -of_objects $nets -filter {DIRECTION == OUT}]
    puts $f "TRACE depth=$depth pin=$pin drivers=$drivers"
    if {$depth > 6} {return}
    foreach driver $drivers {
        set cell [get_cells -of_objects $driver]
        if {[dict exists $seen $cell]} {continue}
        dict set seen $cell 1
        puts $f "CELL $cell [get_property REF_NAME $cell]"
        if {[lsearch -exact [list_property $cell] INIT] >= 0} {puts $f "INIT [get_property INIT $cell]"}
        foreach input [get_pins -of_objects $cell -filter {DIRECTION == IN}] {
            puts $f "INPUT $input [get_nets -of_objects $input]"
        }
        # Stop at sequential boundaries; record all pins above.
        if {[get_property IS_SEQUENTIAL $cell]} {continue}
        foreach input [get_pins -of_objects $cell -filter {DIRECTION == IN}] {trace_pin $input [expr {$depth+1}]}
    }
}
foreach pin [get_pins -of_objects $app -filter {DIRECTION == IN}] {
    set name [get_property REF_PIN_NAME $pin]
    if {$name eq "p_0_in" || $name eq "data_in_TVALID" || [string match {S*} $name] || [string match {CO*} $name]} {
        set seen [dict create]; trace_pin $pin 0
    }
}
close $f
close_design
puts "PASS routed boundary export"
exit
