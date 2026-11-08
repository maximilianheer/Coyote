#ifndef INSPECTION_PREPROCESS_STREAM_HPP
#define INSPECTION_PREPROCESS_STREAM_HPP

#include "sample_positions.hpp"

namespace inspection {

// The caller supplies the length before this function consumes payload beats.
// Iterate over output samples for small inputs, retaining the current word.
// At larger strides, drain skipped words as they arrive. Every raw word is
// consumed, including a partial last word, independent of selected pixels.
template<class Packet, class Pixel>
void preprocess_stream(
    std::uint64_t length,
    hls::stream<Packet>& raw,
    hls::stream<Pixel>& pixels
) {
    SamplePositions positions(length);
    Packet cached;
    std::uint64_t words_read = 0;
    const std::uint64_t word_count = (length + 63) / 64;

    if (length >= std::uint64_t(pixel_count - 1) * 64 + 1) {
        // At least one complete word separates samples; retain the native
        // one-word-per-cycle scan instead of introducing a nested pixel loop.
        for (std::uint64_t word = 0; word < word_count; ++word) {
            #pragma HLS PIPELINE II=1
            Packet packet = raw.read();
            const std::uint64_t position = positions.current();
            if (position / 64 == word) {
                const unsigned lane = position % 64;
                ap_uint<8> byte = packet.data.range(lane * 8 + 7, lane * 8);
                Pixel pixel;
                pixel[0] = typename Pixel::value_type(float(255 - byte) / 255.0f);
                pixels.write(pixel);
                positions.advance();
            }
        }
        return;
    }

    for (unsigned sample = 0; sample < pixel_count; ++sample) {
        const std::uint64_t position = positions.current();
        ap_uint<8> byte = 0;
        if (position < length) {
            const std::uint64_t word = position / 64;
            while (words_read <= word) {
                #pragma HLS PIPELINE II=1
                cached = raw.read();
                ++words_read;
            }
            const unsigned lane = position % 64;
            byte = cached.data.range(lane * 8 + 7, lane * 8);
        }
        // Preserve the production FP32 divide before fixed-point conversion.
        Pixel pixel;
        pixel[0] = typename Pixel::value_type(float(255 - byte) / 255.0f);
        pixels.write(pixel);
        positions.advance();
    }
    while (words_read < word_count) {
        #pragma HLS PIPELINE II=1
        raw.read();
        ++words_read;
    }
}

} // namespace inspection
#endif
