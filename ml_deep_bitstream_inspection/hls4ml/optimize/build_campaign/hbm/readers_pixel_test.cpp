#include "ap_int.h"
#include "ap_fixed.h"
#include "hls_stream.h"
#include "reader_preprocess.hpp"
#include <cassert>
#include <iostream>
#include <vector>
#include <cstring>
#include <dlfcn.h>

using Predict = void (*)(float*, float*);
static Predict predict = nullptr;

struct Pixel {
    using value_type = ap_fixed<16, 6>;
    value_type value;
    value_type& operator[](unsigned) { return value; }
};

static unsigned pattern(std::uint64_t position) {
    return (position * 71 + position / 97) % 256;
}

static void check(std::uint64_t length, std::uint64_t base, unsigned grouping) {
    hls::stream<ap_uint<96>> requests;
    hls::stream<ap_uint<512>> responses;
    hls::stream<Pixel> pixels;
    if (grouping == 0) inspection::scan_requests(length, base, requests);
    else inspection::coalesced_requests(length, base, grouping, requests);
    std::uint64_t previous_end = base;
    std::uint64_t traffic = 0;
    while (!requests.empty()) {
        const auto request = requests.read();
        const std::uint64_t address = request.range(63, 0);
        const unsigned bytes = request.range(95, 64);
        assert(address % 64 == 0 && address >= previous_end && address >= base);
        assert(bytes > 0 && bytes <= (grouping == 0 ? 65536 : 16384));
        assert(address - base < length);
        if (grouping != 0) {
            assert(bytes % 64 == 0);
            assert(address / 2097152 == (address + bytes - 1) / 2097152);
        } else {
            assert(address == previous_end);
            assert(bytes == std::min<std::uint64_t>(65536, length - (address - base)));
        }
        previous_end = address + bytes;
        traffic += bytes;
        for (unsigned offset = 0; offset < bytes; offset += 64) {
            ap_uint<512> word = 0;
            for (unsigned lane = 0; lane < 64; ++lane)
                word.range(lane * 8 + 7, lane * 8) = pattern(address - base + offset + lane);
            responses.write(word);
        }
    }
    if (grouping == 0) {
        assert(traffic == length);
        inspection::scan_responses(length, responses, pixels);
    } else {
        inspection::coalesced_responses(length, grouping, responses, pixels);
    }
    assert(responses.empty());
    std::vector<float> actual_input(65536), expected_input(65536);
    for (std::uint64_t sample = 0; sample < 65536; ++sample) {
        const auto position = length <= 65536 ? sample : sample * (length - 1) / 65535;
        const auto byte = position < length ? pattern(position) : 0;
        const Pixel::value_type expected(float(255 - byte) / 255.0f);
        assert(!pixels.empty());
        const auto actual = pixels.read().value;
        assert(actual == expected);
        actual_input[sample] = float(actual);
        expected_input[sample] = float(255 - byte) / 255.0f;
    }
    assert(pixels.empty());
    // Identical fixed-point pixels must preserve the accepted stock CNN score.
    // Check with the pinned hls4ml CPU bridge as well as comparing every pixel.
    float actual_score = 0, expected_score = 0;
    predict(actual_input.data(), &actual_score);
    predict(expected_input.data(), &expected_score);
    assert(std::memcmp(&actual_score, &expected_score, sizeof(float)) == 0);
}

int main(int argc, char** argv) {
    assert(argc == 2);
    void* library = dlopen(argv[1], RTLD_NOW);
    if (!library) {
        std::cerr << dlerror() << '\n';
        return 1;
    }
    predict = reinterpret_cast<Predict>(dlsym(library, "iteration_model_float"));
    assert(predict);
    const std::vector<std::uint64_t> lengths = {
        0, 1, 63, 64, 65, 4095, 4096, 4097, 65535, 65536, 65537,
        1048576, 2097151, 2097152, 2097153, 4194240, 4194241, 4194242,
        4194304, 5540996, 12004440, 16777216, 18876484, 30323588,
        34162708, 41278872, 48540364, 55676772, 67108864, 134217664
    };
    unsigned cases = 0;
    for (auto length : lengths) {
        for (unsigned grouping : {0, 1, 2, 4, 8}) {
            check(length, 0x400000, grouping);
            ++cases;
        }
    }
    // An intentionally near-page-end base catches boundary splits independent
    // of the deployment allocator's usual hugepage-aligned base.
    for (unsigned grouping : {1, 2, 4, 8}) {
        check(2097153, 0x1fffc0, grouping);
        check(134217664, 0x1fffc0, grouping);
        cases += 2;
    }
    std::cout << "PASS " << cases << " reader cases; all 65,536 fixed-point pixels, "
              << "ordered nonduplicate descriptors, limits and page splits\n";
}
