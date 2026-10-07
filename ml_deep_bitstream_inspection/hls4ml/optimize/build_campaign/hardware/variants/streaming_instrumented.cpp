#include "model_wrapper.hpp"
#include "streaming_helpers.hpp"
void model_wrapper(hls::stream<axi_s> &data_in, hls::stream<axi_s> &data_out,
    volatile unsigned &pp_start, volatile unsigned &pp_end,
    volatile unsigned &cnn_start, volatile unsigned &logit,
    volatile unsigned &produced_tokens) {
    #pragma HLS INTERFACE ap_ctrl_none port=return
    #pragma HLS INTERFACE axis register port=data_in name=data_in
    #pragma HLS INTERFACE axis register port=data_out name=data_out
    #pragma HLS INTERFACE ap_none port=pp_start
    #pragma HLS INTERFACE ap_none port=pp_end
    #pragma HLS INTERFACE ap_none port=cnn_start
    #pragma HLS INTERFACE ap_none port=logit
    #pragma HLS INTERFACE ap_none port=produced_tokens
    #pragma HLS DATAFLOW
    hls::stream<input_t> bitstream_input("bitstream_input");
    #pragma HLS STREAM variable=bitstream_input depth=65536
    hls::stream<result_t> result_stream("result_stream");
    #pragma HLS STREAM variable=result_stream depth=1
    hls::stream<bool> kick("kick");
    #pragma HLS STREAM variable=kick depth=1
    benchmark::streaming_preprocess(data_in, bitstream_input, kick, pp_start, pp_end, produced_tokens);
    benchmark::streaming_infer(kick, bitstream_input, result_stream, cnn_start);
    benchmark::streaming_publish(result_stream, data_out, logit);
}
