    -- Same passive FIFO event copies as the Verilog export.
    observer_pixel_write <= not(ap_rst_n_inv) and bitstream_input_full_n and
        raw_bitstream_downsample_to_input_stream_U0_bitstream_input_write;
    observer_pixel_read <= not(ap_rst_n_inv) and bitstream_input_empty_n and
        production_infer_and_publish_U0_bitstream_input_read;
