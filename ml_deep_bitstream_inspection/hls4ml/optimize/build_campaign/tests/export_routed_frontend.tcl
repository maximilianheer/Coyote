# Read-only export of the remaining D_I integration blocks.
if {$argc != 2} {error "usage: export_routed_frontend.tcl CHECKPOINT OUTPUT_DIR"}
set output [file normalize [lindex $argv 1]]
file mkdir $output
open_checkpoint [lindex $argv 0]
set cnn [get_cells -hier -filter {REF_NAME == cnn_wrapper_hls_ip}]
if {[llength $cnn]!=1} {error "expected exactly one CNN"}
set parent [file dirname [get_property NAME $cnn]]
set f [open "$output/ports.tsv" w]
puts $f "block\tpin\tdirection\tnets"
foreach {label relative} {preprocess checker_path.preprocess fifo checker_path.pixel_fifo control control} {
    set cell [get_cells -quiet "$parent/$relative"]
    if {[llength $cell]!=1} {error "missing block $parent/$relative"}
    puts "EXPORT $label $cell [get_property REF_NAME $cell]"
    write_verilog -force -mode funcsim -cell $cell "$output/${label}_routed.v"
    foreach pin [get_pins -of_objects $cell] {
        puts $f "$label\t[get_property REF_PIN_NAME $pin]\t[get_property DIRECTION $pin]\t[get_nets -of_objects $pin]"
    }
}
close $f
close_design
puts "PASS routed frontend export"
exit
