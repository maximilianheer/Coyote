// Passive copies of the existing internal FIFO's accepted write/read events.
// Export hook verifies both FIFO clock-enables are tied high and depth is 32.
output observer_pixel_write;
output observer_pixel_read;
assign observer_pixel_write = !ap_rst_n_inv && bitstream_input_full_n &&
    raw_bitstream_downsample_to_input_stream_U0_bitstream_input_write;
assign observer_pixel_read = !ap_rst_n_inv && bitstream_input_empty_n &&
    production_infer_and_publish_U0_bitstream_input_read;
