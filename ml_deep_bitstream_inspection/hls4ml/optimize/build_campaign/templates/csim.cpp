#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <fstream>
#include <vector>
#include "model_wrapper.hpp"
#include "streaming_helpers.hpp"
void baseline_wrapper(hls::stream<axi_s>&, hls::stream<axi_s>&);
static unsigned char byte_at(size_t i) {return (i*131+i/11+17)&255;}
static void raw(hls::stream<axi_s>& in, size_t n) {
    axi_s h; h.data=n; h.keep=-1; h.strb=-1; h.last=n==0; in.write(h);
    for(size_t i=0;i<n;i+=64) {
        axi_s p; p.data=0;p.keep=0;p.strb=0;p.last=i+64>=n;
        for(size_t b=0;b<64 && i+b<n;b++) {
            p.data.range(b*8+7,b*8)=byte_at(i+b);p.keep[b]=1;p.strb[b]=1;
        }
        in.write(p);
    }
}
static input_t::value_type expected(size_t i,size_t n) {
    size_t j=n>65536 ? i*(n-1)/65535 : i;
    unsigned char b=j<n ? byte_at(j):0;
    return input_t::value_type(float(255-b)/255.0f);
}
static void prepared(hls::stream<axi_s>& in,size_t n) {
    for(size_t i=0;i<65536;i+=16) {
        axi_s p;p.data=0;p.keep=-1;p.strb=-1;p.last=i+16==65536;
        for(size_t b=0;b<16;b++) {
            float f=float(expected(i+b,n));uint32_t bits;std::memcpy(&bits,&f,4);
            p.data.range(b*32+31,b*32)=bits;
        }
        in.write(p);
    }
}
int main() {
    std::ofstream rtl_expected("rtl_expected.txt");
    for(size_t n: {size_t(0),size_t(1),size_t(63),size_t(64),size_t(65),
        size_t(65535),size_t(65536),size_t(65537),size_t(4194240),size_t(4194241),size_t(4194242)}) {
        hls::stream<axi_s> in;hls::stream<input_t> out;raw(in,n);
        zero_in_raw::raw_bitstream_downsample_to_input_stream(in,out);
        assert(in.empty());assert(out.size()==65536);
        hls::stream<axi_s> fast_in; hls::stream<input_t> fast_out; hls::stream<bool> kick;
        volatile unsigned ps=0,pe=0,count=0;
        raw(fast_in,n);
        benchmark::streaming_preprocess(fast_in,fast_out,kick,ps,pe,count);
        assert(fast_in.empty() && fast_out.size()==65536 && count==65536);
        assert(kick.read());
        for(size_t i=0;i<65536;i++) {
            auto pristine=out.read()[0];
            assert(pristine==expected(i,n)); assert(fast_out.read()[0]==pristine);
        }
    }
    for(size_t n: {size_t(0),size_t(1),size_t(63),size_t(64),size_t(65),size_t(65535),size_t(65536),size_t(65537),size_t(4194240),size_t(4194241),size_t(4194242)}) {
        hls::stream<axi_s> in,out,ref_in,ref_out;
        if(BENCH_VARIANT==5) prepared(in,n);else raw(in,n);
#if BENCH_VARIANT == 6
        volatile unsigned ps=0,pe=0,cs=0,logit=0,count=0;
        model_wrapper(in,out,ps,pe,cs,logit,count); assert(count==65536);
#elif defined(BENCH_PHASE)
        volatile unsigned phase=0;model_wrapper(in,out,phase);assert(phase==0);
#else
        model_wrapper(in,out);
#endif
        assert(in.empty());assert(out.size()==1);axi_s result=out.read();
        // Production CNN adapter does not set TLAST; CSR result capture uses TVALID.
        if (BENCH_VARIANT==3 || BENCH_VARIANT==4) assert(result.last==1);
        uint32_t actual=result.data.range(31,0).to_uint(),wanted=0;
        if(BENCH_VARIANT==3) wanted=n;
        else if(BENCH_VARIANT==4) {
            for(size_t i=0;i<65536;i++) wanted+=expected(i,n).range(15,0).to_uint();
        } else {
            raw(ref_in,n);baseline_wrapper(ref_in,ref_out);
            assert(ref_in.empty());wanted=ref_out.read().data.range(31,0).to_uint();
        }
        if(actual!=wanted) {std::cerr<<"Parity failure n="<<n<<" actual="<<actual<<" expected="<<wanted<<"\n";return 1;}
        rtl_expected<<std::dec<<n<<" "<<std::hex<<actual<<"\n";
        std::cout<<"PASS variant="<<BENCH_VARIANT<<" bytes="<<n<<" bits="<<actual<<"\n";
    }
    std::cout<<"PASS preprocessing boundaries and wrapper parity\n";
}
