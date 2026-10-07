#include "model_wrapper.hpp"
#include "benchmark_helpers.hpp"

void model_wrapper(hls::stream<axi_s> &data_in, hls::stream<axi_s> &data_out,
                   volatile unsigned int &phase) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=data_in name=data_in
    #pragma HLS INTERFACE axis register port=data_out name=data_out
    #pragma HLS INTERFACE ap_none port=phase

    phase = 1;
    hls::stream<input_t> bitstream_input("bitstream_input");
    #pragma HLS STREAM variable=bitstream_input depth=65536
    benchmark::preprocess(data_in, bitstream_input);
    phase = 2;
    ap_uint<32> sum = benchmark::checksum(bitstream_input);
    axi_s out = benchmark::diagnostic_result(sum);
    phase = 3;
    data_out.write(out);
    phase = 0;
}
