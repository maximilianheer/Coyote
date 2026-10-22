#include "model_types.hpp"
#include "frame_start.hpp"
void cnn_wrapper(hls::stream<input_t>& pixels, hls::stream<axi_s>& data_out) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=pixels
    #pragma HLS INTERFACE axis register port=data_out
    hls::stream<result_t> result("result");
    #pragma HLS STREAM variable=result depth=1
    benchmark::wait_for_first_pixel(pixels);
    iteration_model(pixels, result);
    nnet::data_to_axi_stream<result_t, float, 1, 512, 32>(result, data_out);
}
