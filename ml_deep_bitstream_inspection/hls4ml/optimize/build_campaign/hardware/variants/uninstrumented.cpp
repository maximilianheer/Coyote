#include "model_wrapper.hpp"
#include "benchmark_helpers.hpp"

void model_wrapper(hls::stream<axi_s> &data_in, hls::stream<axi_s> &data_out) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=data_in name=data_in
    #pragma HLS INTERFACE axis register port=data_out name=data_out

    hls::stream<input_t> bitstream_input("bitstream_input");
    #pragma HLS STREAM variable=bitstream_input depth=65536
    benchmark::preprocess(data_in, bitstream_input);
    hls::stream<result_t> result_stream("result_stream");
    #pragma HLS STREAM variable=result_stream depth=1
    benchmark::infer(bitstream_input, result_stream);
    benchmark::publish(result_stream, data_out);
}
