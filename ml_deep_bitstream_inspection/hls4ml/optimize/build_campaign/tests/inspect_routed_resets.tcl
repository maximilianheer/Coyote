if {$argc != 2} {error "usage: inspect_routed_resets.tcl CHECKPOINT OUTPUT_DIR"}
set output [file normalize [lindex $argv 1]]
open_checkpoint [lindex $argv 0]
set f [open "$output/reset_drivers.tsv" w]
puts $f "net\tdriver\ttype\tproperty\tvalue"
set nets [get_nets -hier -filter {NAME =~ *peripheral_aresetn*repN*}]
puts "RESET_NETS [llength $nets]"
foreach net $nets {
    foreach pin [get_pins -leaf -of_objects [get_nets -segments $net] -filter {DIRECTION == OUT}] {
        set cell [get_cells -of_objects $pin]
        set type [get_property REF_NAME $cell]
        foreach prop [list_property $cell] {
            if {[regexp {^(INIT|IS_)} $prop]} {
                puts $f "$net\t$pin\t$type\t$prop\t[get_property $prop $cell]"
            }
        }
        foreach input [get_pins -of_objects $cell -filter {DIRECTION == IN}] {
            set connected [get_nets -segments -of_objects $input]
            set drivers [get_pins -leaf -of_objects $connected -filter {DIRECTION == OUT}]
            puts $f "$net\t$pin\t$type\t[get_property REF_PIN_NAME $input]\t$connected DRIVERS=$drivers"
        }
    }
}
close $f
close_design
puts "PASS routed reset inspection"
exit
