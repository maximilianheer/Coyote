#include "model_types.hpp"
#include "direct_preprocess.hpp"
void preprocess_wrapper(hls::stream<axi_s>& data_in,hls::stream<input_t>& pixels) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=data_in
    #pragma HLS INTERFACE axis register port=pixels
    benchmark::direct_preprocess(data_in,pixels);
}
