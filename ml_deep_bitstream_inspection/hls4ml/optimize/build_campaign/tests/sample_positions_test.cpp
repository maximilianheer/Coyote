#include <cassert>
#include <cstdint>
#include <iostream>
#include "sample_positions.hpp"

int main() {
    const std::uint64_t lengths[] = {
        0, 1, 63, 64, 65, 4095, 4096, 4097, 65535, 65536, 65537,
        1048576, 2097152, 4194240, 4194241, 4194242, 134217664
    };
    for (auto length : lengths) {
        inspection::SamplePositions positions(length);
        for (std::uint64_t i = 0; i < inspection::pixel_count; ++i) {
            const auto expected = length <= inspection::pixel_count
                ? i : i * (length - 1) / (inspection::pixel_count - 1);
            assert(positions.current() == expected);
            positions.advance();
        }
    }
    std::cout << "PASS: exact sample indices for 17 boundary and workload sizes\n";
}
