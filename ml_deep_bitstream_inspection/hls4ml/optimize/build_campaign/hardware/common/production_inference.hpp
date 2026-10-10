#ifndef BENCH_PRODUCTION_INFERENCE_HPP
#define BENCH_PRODUCTION_INFERENCE_HPP
#include "model_wrapper.hpp"
#include "frame_start.hpp"

namespace benchmark {
// One controlled CNN invocation, followed by the unchanged production float
// converter. Keep nested CNN DATAFLOW inside this sequential process so the
// outer preprocessing DATAFLOW does not change the CNN to ap_ctrl_chain.
static void production_infer_and_publish(hls::stream<input_t>& pixels,
                                         hls::stream<axi_s>& data_out) {
    #pragma HLS INLINE OFF
    hls::stream<result_t> result("production_result");
    #pragma HLS STREAM variable=result depth=1
    wait_for_first_pixel(pixels);
    prod_res256_manualA_coyote_accel(pixels,result);
    nnet::data_to_axi_stream<result_t,float,1,COYOTE_AXI_STREAM_BITS,8*sizeof(float)>(result,data_out);
}
}
#endif
