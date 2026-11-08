#include "ap_int.h"
#include "ap_fixed.h"
#include "ap_axi_sdata.h"
#include "hls_stream.h"
#include <cassert>
#include <cstdint>
#include <iostream>
#include "preprocess_stream.hpp"

struct Pixel {
    using value_type = ap_fixed<16, 6>;
    value_type value;
    value_type& operator[](unsigned) { return value; }
};

using Packet = ap_axiu<512, 0, 0, 0>;

static unsigned pattern(std::uint64_t position) {
    return (position * 131 + position / 97 + 29) % 256;
}

int main() {
    for (std::uint64_t length : {
        0ULL, 1ULL, 63ULL, 64ULL, 65ULL, 4095ULL, 4096ULL, 4097ULL,
        65535ULL, 65536ULL, 65537ULL, 1048576ULL, 2097152ULL,
        4194240ULL, 4194241ULL, 4194242ULL
    }) {
        hls::stream<Packet> raw;
        hls::stream<Pixel> pixels;
        for (std::uint64_t word = 0; word < (length + 63) / 64; ++word) {
            Packet packet;
            packet.data = 0;
            packet.keep = 0;
            for (unsigned lane = 0; lane < 64; ++lane) {
                const auto index = word * 64 + lane;
                if (index < length) {
                    packet.data.range(lane * 8 + 7, lane * 8) = pattern(index);
                    packet.keep[lane] = 1;
                }
            }
            packet.last = word + 1 == (length + 63) / 64;
            raw.write(packet);
        }
        inspection::preprocess_stream(length, raw, pixels);
        assert(raw.empty());
        for (std::uint64_t i = 0; i < 65536; ++i) {
            const auto position = length <= 65536 ? i : i * (length - 1) / 65535;
            const unsigned byte = position < length ? pattern(position) : 0;
            const Pixel::value_type expected(float(255 - byte) / 255.0f);
            assert(!pixels.empty());
            assert(pixels.read().value == expected);
        }
        assert(pixels.empty());
    }
    std::cout << "PASS: exact 65,536 normalized pixels and full drain for 16 sizes\n";
}
