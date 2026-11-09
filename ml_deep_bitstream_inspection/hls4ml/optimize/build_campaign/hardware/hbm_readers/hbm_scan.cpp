#include "model_types.hpp"
#include "reader_preprocess.hpp"

void hbm_scan(hls::stream<ap_uint<192>>& frame,
              hls::stream<ap_uint<96>>& requests,
              hls::stream<ap_uint<512>>& words,
              hls::stream<input_t>& pixels) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=frame
    #pragma HLS INTERFACE axis register port=requests
    #pragma HLS INTERFACE axis register port=words
    #pragma HLS INTERFACE axis register port=pixels
    const auto config = frame.read();
    const std::uint64_t base = config.range(63, 0);
    const std::uint64_t length = config.range(127, 64);
    #pragma HLS DATAFLOW
    inspection::scan_requests(length, base, requests);
    inspection::scan_responses(length, words, pixels);
}
