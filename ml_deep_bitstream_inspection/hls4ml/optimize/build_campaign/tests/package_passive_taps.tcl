if {$argc != 2} {error "Expected isolated IP directory and maintained snippet directory"}
set ipdir [file normalize [lindex $argv 0]]
set snippets [file normalize [lindex $argv 1]]
source "$snippets/export_fifo_taps.tcl"
passive_taps::package $ipdir $snippets
create_project passive_export_test "[pwd]/catalog_project" -part xcu55c-fsvh2892-2L-e -force
set_property target_language Verilog [current_project]
set_property ip_repo_paths [file dirname $ipdir] [current_project]
update_ip_catalog
create_ip -name model_wrapper_hls_ip -vendor user.org -library hls -version 1.0 -module_name model_wrapper_hls_ip
generate_target instantiation_template [get_ips model_wrapper_hls_ip]
set templates [glob -nocomplain "[pwd]/catalog_project/passive_export_test.gen/sources_1/ip/model_wrapper_hls_ip/*.veo"]
if {[llength $templates]!=1} {error "Missing generated IP instantiation template"}
set template [passive_taps::read_file [lindex $templates 0]]
foreach port {observer_pixel_write observer_pixel_read} {
    if {[string first ".${port}(" $template]<0} {error "Tap absent from catalog-generated interface: $port"}
}
puts "PASS passive tap IP catalog interface"
close_project
exit
