logic [15:0] preprocessed_pixel, cnn_pixel;
logic pixel_valid, pixel_ready, cnn_valid, cnn_ready;
logic [5:0] pixel_occupancy;
logic [511:0] cnn_result;

elastic_fifo #(.WIDTH(16), .DEPTH(32)) pixel_fifo (
    .clk(aclk), .rst_n(aresetn),
    .in_data(preprocessed_pixel), .in_valid(pixel_valid), .in_ready(pixel_ready),
    .out_data(cnn_pixel), .out_valid(cnn_valid), .out_ready(cnn_ready),
    .occupancy(pixel_occupancy)
);
cnn_wrapper_hls_ip cnn (
    .ap_clk(aclk), .ap_rst_n(aresetn),
    .pixels_TDATA(cnn_pixel), .pixels_TVALID(cnn_valid), .pixels_TREADY(cnn_ready),
    .data_out_TDATA(cnn_result), .data_out_TKEEP(), .data_out_TSTRB(),
    .data_out_TLAST(), .data_out_TVALID(result_valid), .data_out_TREADY(1'b1)
);
assign result_bits = cnn_result[31:0];
