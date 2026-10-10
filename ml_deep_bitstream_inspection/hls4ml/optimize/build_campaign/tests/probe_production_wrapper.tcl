puts "PROBE_START"
puts "PROBE_SCOPES [get_scopes]"
set top [regsub {/[^/]+$} [lindex [get_scopes] 0] {}]
puts "PROBE_ROOT <$top>"
if {[catch {get_value $top/frame} value]} {puts "PROBE_ROOT_ERROR $value";quit}
foreach interval {100 1200} {
    run $interval us
    puts "PROBE_TIME [current_time]"
    foreach name {frame results data_in_TVALID data_in_TREADY data_out_TVALID data_out_TREADY data_out_TDATA} {
        if {[catch {get_value $top/$name} value]} {
            puts "PROBE_UNAVAILABLE $name $value"
        } else {puts "PROBE_TOP $name $value"}
    }
    foreach name {bitstream_input_num_data_valid bitstream_input_full_n bitstream_input_empty_n layer39_out_num_data_valid layer39_out_full_n layer39_out_empty_n raw_bitstream_downsample_to_input_stream_U0_ap_start raw_bitstream_downsample_to_input_stream_U0_ap_ready raw_bitstream_downsample_to_input_stream_U0_ap_done raw_bitstream_downsample_to_input_stream_U0_ap_idle prod_res256_manualA_coyote_accel_U0_ap_start prod_res256_manualA_coyote_accel_U0_ap_done prod_res256_manualA_coyote_accel_U0_ap_ready prod_res256_manualA_coyote_accel_U0_ap_idle} {
        if {[catch {get_value $top/dut/$name} value]} {
            puts "PROBE_UNAVAILABLE $name $value"
        } else {puts "PROBE_CORE $name $value"}
    }
}
quit
