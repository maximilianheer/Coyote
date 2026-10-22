#ifndef ITERATION_MODEL_TYPES_HPP
#define ITERATION_MODEL_TYPES_HPP
#include "hls_stream.h"
#include "ap_axi_sdata.h"
#define COYOTE_AXI_STREAM_BITS 512
typedef ap_axiu<512, 0, 0, 0> axi_s;
#include "firmware/iteration_model.h"
#include "firmware/zero_in_raw_downsample.hpp"
#include "nnet_axi_utils_stream.h"
#endif
