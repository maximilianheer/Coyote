# Read-only inspection of the implemented checkpoint; no synthesis/place/route.
if {$argc != 2} {error "usage: export_routed_checker.tcl CHECKPOINT OUTPUT_DIR"}
set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
file mkdir $output
open_checkpoint $checkpoint
set cores [get_cells -hier -filter {REF_NAME == cnn_wrapper_hls_ip}]
if {[llength $cores] != 1} {error "expected one CNN core, got $cores"}
set core [lindex $cores 0]
puts "EXPORTED_CORE $core"
write_verilog -force -mode funcsim -cell $core "$output/cnn_routed.v"
set f [open "$output/memory_properties.tsv" w]
puts $f "cell\ttype\tproperty\tvalue"
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && (REF_NAME =~ RAMB* || REF_NAME =~ URAM*)}] {
    if {![string match "$core/*" $cell]} {continue}
    foreach prop [list_property $cell] {
        if {[regexp {^(INIT|SRVAL|READ_WIDTH|WRITE_WIDTH|DO[A-B]_REG|WRITE_MODE)} $prop]} {
            puts $f "$cell\t[get_property REF_NAME $cell]\t$prop\t[get_property $prop $cell]"
        }
    }
}
close $f
close_design
puts "PASS routed checker export"
exit
