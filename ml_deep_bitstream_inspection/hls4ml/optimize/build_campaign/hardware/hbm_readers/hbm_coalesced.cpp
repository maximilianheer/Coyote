#include "model_types.hpp"
#include "reader_preprocess.hpp"

void hbm_coalesced(hls::stream<ap_uint<192>>& frame,
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
    const unsigned grouping = config.range(191, 128);
    #pragma HLS DATAFLOW
    inspection::coalesced_requests(length, base, grouping, requests);
    inspection::coalesced_responses(length, grouping, words, pixels);
}
