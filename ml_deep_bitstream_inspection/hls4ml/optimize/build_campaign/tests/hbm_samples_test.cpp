#include "ap_int.h"
#include "ap_fixed.h"
#include "hls_stream.h"
#include "hbm_samples.hpp"
#include <cassert>
#include <iostream>

struct Pixel {
    using value_type = ap_fixed<16, 6>;
    value_type value;
    value_type& operator[](unsigned) { return value; }
};

static unsigned pattern(std::uint64_t index) { return (index * 71 + index / 97) % 256; }

int main() {
    for (std::uint64_t length : {
        0ULL, 1ULL, 63ULL, 64ULL, 65ULL, 65535ULL, 65536ULL, 65537ULL,
        1048576ULL, 2097152ULL, 4194240ULL, 4194241ULL, 4194242ULL, 134217664ULL
    }) {
        hls::stream<ap_uint<64>> requests;
        hls::stream<ap_uint<512>> responses;
        hls::stream<Pixel> pixels;
        inspection::sample_requests(length, 0x10000, requests);
        std::uint64_t previous = ~std::uint64_t(0);
        while (!requests.empty()) {
            const std::uint64_t address = requests.read();
            assert(address % 64 == 0);
            assert(previous == ~std::uint64_t(0) || address > previous);
            assert(address - 0x10000 < length);
            previous = address;
            ap_uint<512> word = 0;
            for (unsigned lane = 0; lane < 64; ++lane)
                word.range(lane * 8 + 7, lane * 8) = pattern(address - 0x10000 + lane);
            responses.write(word);
        }
        inspection::sample_responses(length, responses, pixels);
        assert(responses.empty());
        for (std::uint64_t i = 0; i < 65536; ++i) {
            const auto position = length <= 65536 ? i : i * (length - 1) / 65535;
            const auto byte = position < length ? pattern(position) : 0;
            const Pixel::value_type expected(float(255 - byte) / 255.0f);
            assert(pixels.read().value == expected);
        }
        assert(pixels.empty());
    }
    std::cout << "PASS: HBM selected requests and exact pixels for 14 sizes\n";
}
