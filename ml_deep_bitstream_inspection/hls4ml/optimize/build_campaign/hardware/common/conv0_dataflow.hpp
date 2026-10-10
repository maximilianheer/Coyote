#ifndef BENCH_CONV0_DATAFLOW_HPP
#define BENCH_CONV0_DATAFLOW_HPP
#include "hls_stream.h"
#include "ap_int.h"
#include "ap_shift_reg.h"

namespace benchmark {
// Production conv0 only: copy each window into the FIFO before arithmetic.
// The generator is the sole owner of mutable line/window state.
typedef ap_uint<400> conv0_window;

template<class DATA, class CONFIG>
void conv0_windows(hls::stream<DATA>& in, hls::stream<conv0_window>& out) {
    #pragma HLS INLINE OFF
    static_assert(CONFIG::in_width == 260 && CONFIG::in_height == 260 &&
                  CONFIG::n_chan == 1 && CONFIG::filt_height == 5 &&
                  CONFIG::filt_width == 5 && CONFIG::stride_width == 2 &&
                  CONFIG::stride_height == 2, "conv0 geometry changed");
    static ap_shift_reg<typename DATA::value_type, 260> lines[4][1];
    #pragma HLS ARRAY_PARTITION variable=lines complete dim=2
    typename DATA::value_type window[25];
    #pragma HLS ARRAY_PARTITION variable=window complete
    unsigned row=0, col=0;
PixelScan:
    for (unsigned i=0; i<67600; ++i) {
        #pragma HLS PIPELINE II=1
        DATA pixel=in.read();
        nnet::shift_line_buffer<DATA,CONFIG>(pixel,lines,window);
        if (row>=4 && col>=4 && !(row&1) && !(col&1)) {
            conv0_window copy;
        CopyWindow:
            for (unsigned j=0;j<25;++j) {
                #pragma HLS UNROLL
                copy.range(j*16+15,j*16)=window[j].range(15,0);
            }
            out.write(copy);
        }
        // Always consume the trailing padded row/column, including after the
        // last emitted window; otherwise the next frame would be misaligned.
        if(col==259) {col=0;++row;} else ++col;
    }
}

template<class DATA, class RESULT, class CONFIG>
void conv0_arithmetic(hls::stream<conv0_window>& in, hls::stream<RESULT>& out,
    typename CONFIG::weight_t weights[200], typename CONFIG::bias_t biases[8]) {
    #pragma HLS INLINE OFF
WindowScan:
    for(unsigned i=0;i<16384;++i) {
        #pragma HLS PIPELINE II=1
        conv0_window copy=in.read();
        typename DATA::value_type window[25];
        typename RESULT::value_type result[8];
        #pragma HLS ARRAY_PARTITION variable=window complete
        #pragma HLS ARRAY_PARTITION variable=result complete
        for(unsigned j=0;j<25;++j) {
            #pragma HLS UNROLL
            window[j].range(15,0)=copy.range(j*16+15,j*16);
        }
        CONFIG::mult_config::template kernel<typename DATA::value_type,
            typename RESULT::value_type,typename CONFIG::mult_config>::dense(window,result,weights,biases);
        RESULT packed;
        for(unsigned j=0;j<8;++j) {
            #pragma HLS UNROLL
            packed[j]=result[j];
        }
        out.write(packed);
    }
}

template<class DATA, class RESULT, class CONFIG>
void conv0_dataflow(hls::stream<DATA>& in, hls::stream<RESULT>& out,
    typename CONFIG::weight_t weights[200], typename CONFIG::bias_t biases[8]) {
    #pragma HLS INLINE OFF
    #pragma HLS DATAFLOW
    hls::stream<conv0_window> windows("conv0_copied_windows");
    #pragma HLS STREAM variable=windows depth=4
    conv0_windows<DATA,CONFIG>(in,windows);
    conv0_arithmetic<DATA,RESULT,CONFIG>(windows,out,weights,biases);
}
}
#endif
