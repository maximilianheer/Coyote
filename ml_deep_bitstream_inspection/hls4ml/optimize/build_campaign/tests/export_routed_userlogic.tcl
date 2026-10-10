# Preserve cross-boundary physical optimization by exporting the whole checker.
if {$argc != 2} {error "usage: export_routed_userlogic.tcl CHECKPOINT OUTPUT_DIR"}
set output [file normalize [lindex $argv 1]]
file mkdir $output
open_checkpoint [lindex $argv 0]
set cnn [get_cells -hier -filter {REF_NAME == cnn_wrapper_hls_ip}]
if {[llength $cnn]!=1} {error "expected one CNN"}
set parent [get_cells [file dirname [get_property NAME $cnn]]]
puts "EXPORT_USERLOGIC $parent [get_property REF_NAME $parent]"
write_verilog -force -mode funcsim -cell $parent "$output/userlogic_routed.v"
set f [open "$output/ports.tsv" w]
puts $f "pin\tdirection\tnets"
foreach pin [get_pins -of_objects $parent] {
    puts $f "[get_property REF_PIN_NAME $pin]\t[get_property DIRECTION $pin]\t[get_nets -quiet -of_objects $pin]"
}
close $f
set f [open "$output/reset_drivers.tsv" w]
puts $f "pin\tdriver\ttype\tINIT\tclock\tdata\tCE\tR"
foreach pin [get_pins -of_objects $parent -filter {DIRECTION == IN}] {
    set name [get_property REF_PIN_NAME $pin]
    if {![string match "*aresetn*" $name]} {continue}
    set nets [get_nets -segments -of_objects $pin]
    set drivers [get_pins -leaf -of_objects $nets -filter {DIRECTION == OUT}]
    if {[llength $drivers]!=1} {error "reset $name has unexpected drivers $drivers"}
    set driver [lindex $drivers 0];set cell [get_cells -of_objects $driver]
    set fields [list $name $driver [get_property REF_NAME $cell] [get_property INIT $cell]]
    foreach field {C D CE R} {
        lappend fields [get_nets -of_objects [get_pins "$cell/$field"]]
    }
    puts $f [join $fields "\t"]
}
close $f
close_design
puts "PASS routed userlogic export"
exit
