#ifndef INSPECTION_READER_PREPROCESS_HPP
#define INSPECTION_READER_PREPROCESS_HPP

#include "sample_positions.hpp"
#include "hbm_samples.hpp"

namespace inspection {

// Descriptor low 64 bits = aligned virtual address; high 32 bits = byte count.
inline void descriptor(hls::stream<ap_uint<96>>& requests,
                       std::uint64_t address, unsigned bytes) {
    ap_uint<96> value = 0;
    value.range(63, 0) = address;
    value.range(95, 64) = bytes;
    requests.write(value);
}

inline void scan_requests(std::uint64_t length, std::uint64_t base,
                          hls::stream<ap_uint<96>>& requests) {
    for (std::uint64_t offset = 0; offset < length; offset += 65536) {
        #pragma HLS PIPELINE II=1
        const auto remaining = length - offset;
        descriptor(requests, base + offset, remaining > 65536 ? 65536 : unsigned(remaining));
    }
}

template<class Pixel>
void scan_responses(std::uint64_t length, hls::stream<ap_uint<512>>& words,
                    hls::stream<Pixel>& pixels) {
    SamplePositions positions(length);
    const auto total_words = (length + 63) / 64;
    if (length >= std::uint64_t(pixel_count - 1) * 64 + 1) {
        // At large strides there is at most one selected byte in each word.
        // Consume nonselected words at one word/cycle instead of looping pixels.
        for (std::uint64_t word = 0; word < total_words; ++word) {
            #pragma HLS PIPELINE II=1
            const ap_uint<512> value = words.read();
            const auto position = positions.current();
            if (position / 64 == word) {
                const unsigned lane = position % 64;
                const ap_uint<8> byte = value.range(lane * 8 + 7, lane * 8);
                Pixel pixel;
                pixel[0] = typename Pixel::value_type(float(255 - byte) / 255.0f);
                pixels.write(pixel);
                positions.advance();
            }
        }
        return;
    }
    ap_uint<512> cached = 0;
    std::uint64_t consumed = 0;
    for (unsigned sample = 0; sample < pixel_count; ++sample) {
        const auto position = positions.current();
        ap_uint<8> byte = 0;
        if (position < length) {
            while (consumed <= position / 64) {
                #pragma HLS PIPELINE II=1
                cached = words.read();
                ++consumed;
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

inline void coalesced_requests(std::uint64_t length, std::uint64_t base,
                               unsigned grouping, hls::stream<ap_uint<96>>& requests) {
    SamplePositions positions(length);
    std::uint64_t covered_end = 0;
    for (unsigned group = 0; group < pixel_count; group += grouping) {
        const auto first = positions.current();
        auto last = first;
        for (unsigned member = 0; member < grouping && group + member < pixel_count; ++member) {
            #pragma HLS PIPELINE II=1
            if (positions.current() < length) last = positions.current();
            positions.advance();
        }
        if (first < length) {
            auto begin = first / 64 * 64;
            const auto end = last / 64 * 64 + 64;
            // A word shared by adjacent groups is already available in cache.
            if (begin < covered_end) begin = covered_end;
            while (begin < end) {
                #pragma HLS PIPELINE II=1
                const auto absolute = base + begin;
                const unsigned page_remaining = 2097152 - unsigned(absolute % 2097152);
                auto bytes = end - begin;
                if (bytes > 16384) bytes = 16384;
                if (bytes > page_remaining) bytes = page_remaining;
                descriptor(requests, absolute, unsigned(bytes));
                begin += bytes;
            }
            covered_end = end;
        }
    }
}

template<class Pixel>
void coalesced_responses(std::uint64_t length, unsigned grouping,
                         hls::stream<ap_uint<512>>& words, hls::stream<Pixel>& pixels) {
    SamplePositions positions(length);
    ap_uint<512> cached = 0;
    std::uint64_t cached_word = 0;
    std::uint64_t next_word = 0;
    bool have_word = false;
    for (unsigned sample = 0; sample < pixel_count; ++sample) {
        const auto position = positions.current();
        const auto target = position / 64;
        ap_uint<8> byte = 0;
        if ((sample & (grouping - 1)) == 0) {
            // Groups skip gaps; words inside each group are contiguous.
            next_word = have_word && target <= cached_word ? cached_word + 1 : target;
        }
        if (position < length) {
            while (!have_word || cached_word < target) {
                #pragma HLS PIPELINE II=1
                cached = words.read();
                cached_word = next_word;
                ++next_word;
                have_word = true;
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
