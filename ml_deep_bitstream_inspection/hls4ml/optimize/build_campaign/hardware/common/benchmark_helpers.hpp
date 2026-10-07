#ifndef BENCH_HELPERS_HPP
#define BENCH_HELPERS_HPP
#include "model_types.hpp"

namespace benchmark {

// Inline only these thin helpers. Preserve the production functions and the
// sequential preprocessing -> inference -> publication boundaries at each top.
inline void preprocess(hls::stream<axi_s> &in, hls::stream<input_t> &tokens) {
    #pragma HLS INLINE
    zero_in_raw::raw_bitstream_downsample_to_input_stream(in, tokens);
}

inline void load_prepared(hls::stream<axi_s> &in, hls::stream<input_t> &tokens) {
    #pragma HLS INLINE
    nnet::axi_stream_to_data<input_t, float, 65536, COYOTE_AXI_STREAM_BITS, 32>(in, tokens);
}

inline void infer(hls::stream<input_t> &tokens, hls::stream<result_t> &result) {
    #pragma HLS INLINE
    prod_res256_manualA_coyote_accel(tokens, result);
}

inline void publish(hls::stream<result_t> &result, hls::stream<axi_s> &out) {
    #pragma HLS INLINE
    // Keep the production adapter, including its existing TLAST behavior.
    nnet::data_to_axi_stream<result_t, float, 1, COYOTE_AXI_STREAM_BITS, 32>(result, out);
}

inline unsigned long long consume_raw(hls::stream<axi_s> &in) {
    #pragma HLS INLINE
    axi_s header = in.read();
    unsigned long long len = zero_in_raw::read_len_le(header);
    for (unsigned long long i = 0; i < (len + 63) / 64; i++) {
        #pragma HLS PIPELINE II=1
        axi_s discarded = in.read();
    }
    return len;
}

inline ap_uint<32> checksum(hls::stream<input_t> &tokens) {
    #pragma HLS INLINE
    ap_uint<32> sum = 0;
    for (unsigned int i = 0; i < 65536; i++) {
        #pragma HLS PIPELINE II=1
        input_t token = tokens.read();
        sum += ap_uint<16>(token[0].range(15, 0));
    }
    return sum;
}

inline axi_s diagnostic_result(ap_uint<512> value) {
    #pragma HLS INLINE
    axi_s out;
    out.data = value; out.keep = -1; out.strb = -1; out.last = 1;
    return out;
}

} // namespace benchmark
#endif
