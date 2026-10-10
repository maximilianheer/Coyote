# Invoked by the isolated Coyote user-project script, after fresh HLS export
# and before its IP catalog is imported. No prior checkpoints/IP are reused.
set observer_sources [file dirname [info script]]
source "$observer_sources/export_fifo_taps.tcl"
passive_taps::package "$iprepo_dir/model_wrapper_hls_ip" $observer_sources
