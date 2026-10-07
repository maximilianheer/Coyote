#ifndef BENCH_STREAMING_HELPERS_HPP
#define BENCH_STREAMING_HELPERS_HPP
#include "benchmark_helpers.hpp"
namespace benchmark {
// Event bits toggle once per frame and remain stable until the next frame.
// Each port has exactly one writer. The controller snapshots them before DMA.
static void streaming_preprocess(hls::stream<axi_s> &in,
    hls::stream<input_t> &tokens, hls::stream<bool> &kick,
    volatile unsigned &start, volatile unsigned &end, volatile unsigned &count) {
    #pragma HLS INLINE OFF
    static unsigned start_event = 0, end_event = 0;
    axi_s header = in.read();
    start_event ^= 1; start = start_event;
    count = 0;
    kick.write(true);
    const unsigned long long n = zero_in_raw::read_len_le(header);
    const unsigned long long denom = 65535;
    const unsigned long long stride = n > 65536 ? (n-1)/denom : 1;
    const unsigned long long step = n > 65536 ? (n-1)%denom : 0;
    unsigned long long target = 0, rem = 0;
    unsigned written = 0;
    if (n < zero_in_raw::ONE_SAMPLE_PER_BEAT_MIN_LEN) {
        // Adjacent targets differ by at most 64 bytes: at most one new beat
        // per token, with the previous beat cached for targets sharing it.
        axi_s packet;
        unsigned long long cached_beat = ~0ULL;
        for (unsigned i=0; i<65536; ++i) {
            #pragma HLS PIPELINE II=1
            ap_uint<8> byte = 0;
            if (target < n) {
                unsigned long long beat = target / 64;
                if (beat != cached_beat) {
                    packet = in.read(); cached_beat = beat;
                }
                byte = zero_in_raw::get_byte(packet, target % 64);
            }
            zero_in_raw::write_normalized_token(byte, tokens);
            count = ++written;
            target += stride; rem += step;
            if (rem >= denom) { ++target; rem -= denom; }
        }
    } else {
        // Preserve the production one-beat-per-cycle large-input algorithm.
        const unsigned long long beats = (n+63)/64;
        for (unsigned long long beat=0; beat<beats; ++beat) {
            #pragma HLS PIPELINE II=1
            axi_s packet = in.read();
            unsigned long long base = beat*64;
            if (target >= base && target < base+64) {
                zero_in_raw::write_normalized_token(
                    zero_in_raw::get_byte(packet, target-base), tokens);
                count = ++written;
                target += stride; rem += step;
                if (rem >= denom) { ++target; rem -= denom; }
            }
        }
    }
    end_event ^= 1; end = end_event;
}
static void streaming_infer(hls::stream<bool> &kick,
    hls::stream<input_t> &tokens, hls::stream<result_t> &result,
    volatile unsigned &start) {
    #pragma HLS INLINE OFF
    static unsigned event = 0;
    bool frame = kick.read();
    // The branch is a real control dependency on the accepted frame token.
    // An unused read can be scheduled after the CNN call by HLS DATAFLOW,
    // which allowed speculative task starts and extra event toggles.
    if (frame) {
        event ^= 1; start = event;
        prod_res256_manualA_coyote_accel(tokens, result);
    }
}
static void streaming_publish(hls::stream<result_t> &result,
    hls::stream<axi_s> &out, volatile unsigned &logit) {
    #pragma HLS INLINE OFF
    static unsigned event = 0;
    hls::stream<result_t> captured("captured");
    #pragma HLS STREAM variable=captured depth=1
    captured.write(result.read());
    event ^= 1; logit = event;
    benchmark::publish(captured, out);
}
}
#endif
