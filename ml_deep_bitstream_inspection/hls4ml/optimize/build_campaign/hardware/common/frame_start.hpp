#ifndef BENCH_FRAME_START_HPP
#define BENCH_FRAME_START_HPP
#include "hls_stream.h"

namespace benchmark {
// Coyote resets the application during driver insertion, after configuration.
// The CNN must remain idle until a frame arrives: padding can otherwise advance
// hls4ml static position/stride counters which a control-only reset does not clear.
// Observe availability without consuming or modifying the first pixel.
template <typename T>
void wait_for_first_pixel(hls::stream<T>& pixels) {
    #pragma HLS INLINE
    while (pixels.empty()) {
        #pragma HLS PIPELINE II=1
    }
}
}
#endif
