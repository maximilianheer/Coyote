read_verilog -sv [lindex $argv 0]
synth_design -top frame_buffer -part xcu55c-fsvh2892-2L-e -mode out_of_context
set brams [get_cells -hier -filter {REF_NAME =~ RAMB*}]
if {[llength $brams] == 0} {error "Full-frame buffer did not infer block RAM"}
report_utilization -file frame_buffer_utilization.rpt
puts "PASS frame buffer BRAM inference: [llength $brams] RAMB primitives"
exit
