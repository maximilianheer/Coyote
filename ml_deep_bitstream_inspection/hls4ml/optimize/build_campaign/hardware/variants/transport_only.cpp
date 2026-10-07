#include "model_wrapper.hpp"
#include "benchmark_helpers.hpp"

void model_wrapper(hls::stream<axi_s> &data_in, hls::stream<axi_s> &data_out,
                   volatile unsigned int &phase) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=data_in name=data_in
    #pragma HLS INTERFACE axis register port=data_out name=data_out
    #pragma HLS INTERFACE ap_none port=phase

    phase = 1;
    unsigned long long len = benchmark::consume_raw(data_in);
    axi_s out = benchmark::diagnostic_result(len);
    phase = 3;
    data_out.write(out);
    phase = 0;
}
