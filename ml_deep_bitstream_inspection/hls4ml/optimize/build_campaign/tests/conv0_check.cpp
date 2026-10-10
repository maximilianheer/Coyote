#include "firmware/prod_res256_manualA_coyote_accel.h"
#include "firmware/parameters.h"
#include "conv0_dataflow.hpp"
#ifndef __SYNTHESIS__
#include <cassert>
#include <fstream>
#include <iostream>
#include <vector>
#endif
void conv0_candidate(hls::stream<layer2_t>& in,hls::stream<conv0_result_t>& out) {
    benchmark::conv0_dataflow<layer2_t,conv0_result_t,config3>(in,out,w3,b3);
}
void conv0_baseline(hls::stream<layer2_t>& in,hls::stream<conv0_result_t>& out) {
    nnet::conv_2d_cl<layer2_t,conv0_result_t,config3>(in,out,w3,b3);
}
#ifndef __SYNTHESIS__
static layer2_t pixel(unsigned i,unsigned pattern) {
    layer2_t p;
    switch(pattern) {
      case 0: p[0]=0;break;
      case 1: p[0]=1;break;
      case 2: p[0]=(i==0 || i==259 || i==260*259 || i==67599);break;
      case 3: p[0]=((i/260+i%260)&1);break;
      default: p[0].range(15,0)=ap_uint<16>((i*1664525u+1013904223u)>>(pattern%8));break;
    }
    return p;
}
int main() {
    nnet::load_weights_from_txt<weight3_t,200>(w3,"w3.txt");
    nnet::load_weights_from_txt<bias3_t,8>(b3,"b3.txt");
    std::ofstream expected("conv0_expected.txt");
    for(unsigned pattern=0;pattern<8;++pattern) {
        hls::stream<layer2_t> input,ref,win_in;
        hls::stream<conv0_result_t> actual,wanted;
        hls::stream<benchmark::conv0_window> windows;
        for(unsigned i=0;i<67600;++i) {auto p=pixel(i,pattern);input.write(p);ref.write(p);win_in.write(p);}
        benchmark::conv0_windows<layer2_t,config3>(win_in,windows);
        assert(win_in.empty() && windows.size()==16384);
        for(unsigned r=4;r<260;r+=2) for(unsigned c=4;c<260;c+=2) {
            auto w=windows.read();
            for(unsigned y=0;y<5;++y) for(unsigned x=0;x<5;++x)
                assert(w.range((y*5+x)*16+15,(y*5+x)*16).to_uint()==pixel((r-4+y)*260+c-4+x,pattern)[0].range(15,0).to_uint());
        }
        conv0_baseline(ref,wanted);conv0_candidate(input,actual);
        assert(input.empty() && ref.empty() && actual.size()==16384 && wanted.size()==16384);
        while(!actual.empty()) {
            auto a=actual.read(),b=wanted.read();
            for(unsigned j=0;j<8;++j) {assert(a[j]==b[j]);expected<<std::hex<<b[j].range(29,0).to_uint()<<' ';}
            expected<<'\n';
        }
        std::cout<<"PASS conv0 windows and outputs pattern="<<pattern<<std::endl;
    }
}
#endif
