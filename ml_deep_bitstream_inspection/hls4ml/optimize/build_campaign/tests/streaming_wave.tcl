# Save actual pixel FIFO handshakes and external events; omit CNN internals to
# keep the waveform usable across long boundary tests.
log_wave /streaming_rtl_tb/ap_clk
log_wave /streaming_rtl_tb/data_in_TVALID
log_wave /streaming_rtl_tb/data_in_TREADY
log_wave /streaming_rtl_tb/data_out_TVALID
log_wave /streaming_rtl_tb/data_out_TREADY
log_wave /streaming_rtl_tb/pp_start
log_wave /streaming_rtl_tb/pp_end
log_wave /streaming_rtl_tb/cnn_start
log_wave /streaming_rtl_tb/logit
log_wave /streaming_rtl_tb/produced_tokens
log_wave /streaming_rtl_tb/dut/bitstream_input_U/if_read
log_wave /streaming_rtl_tb/dut/bitstream_input_U/if_empty_n
run all
