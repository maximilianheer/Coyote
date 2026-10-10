#include "model_types.hpp"
#include "benchmark_helpers.hpp"
#include "frame_start.hpp"
void cnn_wrapper(hls::stream<input_t>& pixels,hls::stream<axi_s>& data_out) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=pixels
    #pragma HLS INTERFACE axis register port=data_out
    // One model invocation per verdict. The CNN itself retains DATAFLOW and
    // consumes pixels as they arrive. An outer DATAFLOW region ties the model's
    // ap_start high, allowing premature next-frame launches and stalled tails.
    hls::stream<result_t> result("result");
    #pragma HLS STREAM variable=result depth=1
    benchmark::wait_for_first_pixel(pixels);
    prod_res256_manualA_coyote_accel(pixels,result);
    benchmark::publish(result,data_out);
}
