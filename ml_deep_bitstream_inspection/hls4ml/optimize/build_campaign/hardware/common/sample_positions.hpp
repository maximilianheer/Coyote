#ifndef COYOTE_SAMPLE_POSITIONS_HPP
#define COYOTE_SAMPLE_POSITIONS_HPP

#include <cstdint>

namespace inspection {

constexpr unsigned pixel_count = 65536;

// Exact floor(i * (N - 1) / 65535), without a divider in the pixel loop.
// For short inputs positions continue past N; callers emit raw zero padding.
class SamplePositions {
public:
    explicit SamplePositions(std::uint64_t length)
        : position_(0), remainder_(0), stride_(1), step_(0) {
        if (length > pixel_count) {
            stride_ = (length - 1) / (pixel_count - 1);
            step_ = (length - 1) % (pixel_count - 1);
        }
    }

    std::uint64_t current() const { return position_; }

    void advance() {
        position_ += stride_;
        remainder_ += step_;
        if (remainder_ >= pixel_count - 1) {
            ++position_;
            remainder_ -= pixel_count - 1;
        }
    }

private:
    std::uint64_t position_;
    std::uint64_t remainder_;
    std::uint64_t stride_;
    std::uint64_t step_;
};

} // namespace inspection
#endif
