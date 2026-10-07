#ifndef BENCH_INSTRUMENTED_API_HPP
#define BENCH_INSTRUMENTED_API_HPP
#include "model_types.hpp"

void model_wrapper(hls::stream<axi_s> &data_in,
                   hls::stream<axi_s> &data_out,
                   volatile unsigned int &phase);
#endif
