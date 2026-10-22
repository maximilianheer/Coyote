#include "model_types.hpp"
void preprocess_wrapper(hls::stream<axi_s>& data_in, hls::stream<input_t>& pixels) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=data_in
    #pragma HLS INTERFACE axis register port=pixels
    zero_in_raw::raw_bitstream_downsample_to_input_stream(data_in, pixels);
}
