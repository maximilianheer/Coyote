#include "model_types.hpp"
#include "sample_positions.hpp"
#include "hbm_samples.hpp"

void hbm_gather(
    hls::stream<ap_uint<128>>& frame,
    hls::stream<ap_uint<64>>& addresses,
    hls::stream<ap_uint<512>>& words,
    hls::stream<input_t>& pixels
) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=frame
    #pragma HLS INTERFACE axis register port=addresses
    #pragma HLS INTERFACE axis register port=words
    #pragma HLS INTERFACE axis register port=pixels
    ap_uint<128> descriptor = frame.read();
    const std::uint64_t base = descriptor.range(63, 0);
    const std::uint64_t length = descriptor.range(127, 64);
    #pragma HLS DATAFLOW
    inspection::sample_requests(length, base, addresses);
    inspection::sample_responses(length, words, pixels);
}
