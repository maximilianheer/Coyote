#ifndef BENCH_DIRECT_PREPROCESS_HPP
#define BENCH_DIRECT_PREPROCESS_HPP
#include "model_types.hpp"
namespace benchmark {
// Same integer sample locations and normalization as the production pipeline.
// The AXIS output handshake is observed outside HLS for exact pixel timestamps.
inline void direct_preprocess(hls::stream<axi_s>& in,hls::stream<input_t>& out) {
    #pragma HLS INLINE
    axi_s header=in.read();
    const unsigned long long n=zero_in_raw::read_len_le(header);
    const unsigned long long denom=65535;
    const unsigned long long stride=n>65536 ? (n-1)/denom : 1;
    const unsigned long long step=n>65536 ? (n-1)%denom : 0;
    unsigned long long target=0,rem=0;
    if(n<zero_in_raw::ONE_SAMPLE_PER_BEAT_MIN_LEN) {
        axi_s packet;
        unsigned long long cached=~0ULL;
    SmallInput:
        for(unsigned i=0;i<65536;++i) {
            #pragma HLS PIPELINE II=1
            ap_uint<8> byte=0;
            if(target<n) {
                unsigned long long beat=target/64;
                if(beat!=cached) {packet=in.read();cached=beat;}
                byte=zero_in_raw::get_byte(packet,target%64);
            }
            zero_in_raw::write_normalized_token(byte,out);
            target+=stride;rem+=step;
            if(rem>=denom) {++target;rem-=denom;}
        }
    } else {
    LargeInput:
        for(unsigned long long beat=0;beat<(n+63)/64;++beat) {
            #pragma HLS PIPELINE II=1
            axi_s packet=in.read();
            unsigned long long base=beat*64;
            if(target>=base && target<base+64) {
                zero_in_raw::write_normalized_token(zero_in_raw::get_byte(packet,target-base),out);
                target+=stride;rem+=step;
                if(rem>=denom) {++target;rem-=denom;}
            }
        }
    }
}
}
#endif
