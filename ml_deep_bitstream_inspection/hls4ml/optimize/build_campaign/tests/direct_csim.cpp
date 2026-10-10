#include "model_types.hpp"
#include <cassert>
#include <fstream>
#include <iostream>
void preprocess_wrapper(hls::stream<axi_s>&,hls::stream<input_t>&);
void cnn_wrapper(hls::stream<input_t>&,hls::stream<axi_s>&);
int main() {
    std::ofstream result("direct_expected.txt");
    for(size_t n:{size_t(0),size_t(1),size_t(63),size_t(64),size_t(65),size_t(65535),size_t(65536),size_t(65537),size_t(4194240),size_t(4194241),size_t(4194242)}) {
        hls::stream<axi_s> in,out;
        hls::stream<input_t> pixels,checked;
        axi_s h;h.data=n;h.keep=-1;h.strb=-1;h.last=n==0;in.write(h);
        for(size_t i=0;i<n;i+=64) {
            axi_s p;p.data=0;p.keep=-1;p.strb=-1;p.last=i+64>=n;
            for(size_t j=0;j<64 && i+j<n;j++)p.data.range(j*8+7,j*8)=(i+j)*131+(i+j)/11+17;
            in.write(p);
        }
        preprocess_wrapper(in,pixels);
        assert(in.empty() && pixels.size()==65536);
        for(size_t i=0;i<65536;i++) {
            size_t j=n>65536?i*(n-1)/65535:i;
            unsigned char b=j<n?(j*131+j/11+17)&255:0;
            input_t v=pixels.read();assert(v[0]==input_t::value_type(float(255-b)/255.0f));checked.write(v);
        }
        cnn_wrapper(checked,out);
        assert(checked.empty() && out.size()==1);
        result<<std::dec<<n<<' '<<std::hex<<out.read().data.range(31,0).to_uint()<<'\n';
        std::cout<<"PASS direct preprocessing/CNN bytes="<<n<<std::endl;
    }
}
