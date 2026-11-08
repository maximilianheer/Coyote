#ifndef INSPECTION_HBM_SAMPLES_HPP
#define INSPECTION_HBM_SAMPLES_HPP
#include "sample_positions.hpp"

namespace inspection {

// Two DATAFLOW processes decouple address generation from memory responses.
// Each request represents one aligned 64-byte word; duplicate sample words
// generate only one request. The RTL adapter limits actual outstanding reads.
inline void sample_requests(
    std::uint64_t length, std::uint64_t base,
    hls::stream<ap_uint<64>>& addresses
) {
    SamplePositions positions(length);
    std::uint64_t cached_word = ~std::uint64_t(0);
    for (unsigned sample = 0; sample < pixel_count; ++sample) {
        #pragma HLS PIPELINE II=1
        const auto position = positions.current();
        const auto word = position / 64;
        if (position < length && word != cached_word) {
            addresses.write(base + word * 64);
            cached_word = word;
        }
        positions.advance();
    }
}

template<class Pixel>
void sample_responses(
    std::uint64_t length,
    hls::stream<ap_uint<512>>& words,
    hls::stream<Pixel>& pixels
) {
    SamplePositions positions(length);
    std::uint64_t cached_word = ~std::uint64_t(0);
    ap_uint<512> cached = 0;
    for (unsigned sample = 0; sample < pixel_count; ++sample) {
        #pragma HLS PIPELINE II=1
        const auto position = positions.current();
        const auto word = position / 64;
        ap_uint<8> byte = 0;
        if (position < length) {
            if (word != cached_word) {
                cached = words.read();
                cached_word = word;
            }
            const unsigned lane = position % 64;
            byte = cached.range(lane * 8 + 7, lane * 8);
        }
        Pixel pixel;
        pixel[0] = typename Pixel::value_type(float(255 - byte) / 255.0f);
        pixels.write(pixel);
        positions.advance();
    }
}

} // namespace inspection
#endif
