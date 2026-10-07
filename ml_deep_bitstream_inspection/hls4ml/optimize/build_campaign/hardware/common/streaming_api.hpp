#ifndef BENCH_STREAMING_API_HPP
#define BENCH_STREAMING_API_HPP
#include "model_types.hpp"
void model_wrapper(hls::stream<axi_s> &data_in, hls::stream<axi_s> &data_out,
    volatile unsigned &pp_start, volatile unsigned &pp_end,
    volatile unsigned &cnn_start, volatile unsigned &logit,
    volatile unsigned &produced_tokens);
#endif
