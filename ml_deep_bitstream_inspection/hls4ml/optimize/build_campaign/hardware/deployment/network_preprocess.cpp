#include "model_types.hpp"
#include "preprocess_stream.hpp"

void network_preprocess(
    hls::stream<ap_uint<64>>& lengths,
    hls::stream<axi_s>& raw,
    hls::stream<input_t>& pixels
) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=lengths
    #pragma HLS INTERFACE axis register port=raw
    #pragma HLS INTERFACE axis register port=pixels
    const std::uint64_t length = lengths.read();
    inspection::preprocess_stream(length, raw, pixels);
}
