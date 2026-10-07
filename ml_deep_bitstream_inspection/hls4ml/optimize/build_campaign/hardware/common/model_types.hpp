#ifndef BENCH_MODEL_TYPES_HPP
#define BENCH_MODEL_TYPES_HPP

#include "hls_stream.h"
#include "ap_axi_sdata.h"

#define COYOTE_AXI_STREAM_BITS 512
typedef ap_axiu<COYOTE_AXI_STREAM_BITS, 0, 0, 0> axi_s;

// These files are copied byte-for-byte from the frozen production package.
#include "firmware/prod_res256_manualA_coyote_accel.h"
#include "firmware/nnet_utils/nnet_axi_utils.h"
#include "firmware/nnet_utils/nnet_axi_utils_stream.h"
#include "firmware/zero_in_raw_downsample.hpp"

#endif
