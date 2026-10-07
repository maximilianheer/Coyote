#ifndef BENCH_UNINSTRUMENTED_API_HPP
#define BENCH_UNINSTRUMENTED_API_HPP
#include "model_types.hpp"

void model_wrapper(hls::stream<axi_s> &data_in,
                   hls::stream<axi_s> &data_out);
#endif
