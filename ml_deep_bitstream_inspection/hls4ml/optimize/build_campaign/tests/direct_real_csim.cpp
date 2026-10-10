#include "model_types.hpp"
#include <cassert>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>
void preprocess_wrapper(hls::stream<axi_s>&,hls::stream<input_t>&);
void cnn_wrapper(hls::stream<input_t>&,hls::stream<axi_s>&);
int main(int argc,char**argv) {
    assert(argc>1);
    for(int file=1;file<argc;++file) {
        std::ifstream f(argv[file],std::ios::binary);assert(f.good());
        std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(f)),{});
        assert(bytes.size()>1024); // Reject LFS pointer files and missing inputs.
        hls::stream<axi_s> in,out;hls::stream<input_t> pixels,checked;
        axi_s h;h.data=bytes.size();h.keep=-1;h.strb=-1;h.last=0;in.write(h);
        for(size_t i=0;i<bytes.size();i+=64) {
            axi_s p;p.data=0;p.keep=-1;p.strb=-1;p.last=i+64>=bytes.size();
            for(size_t j=0;j<64 && i+j<bytes.size();j++)p.data.range(j*8+7,j*8)=bytes[i+j];
            in.write(p);
        }
        preprocess_wrapper(in,pixels);assert(in.empty() && pixels.size()==65536);
        for(size_t i=0;i<65536;i++) {
            size_t j=bytes.size()>65536?i*(bytes.size()-1)/65535:i;
            unsigned char b=j<bytes.size()?bytes[j]:0;
            auto p=pixels.read();assert(p[0]==input_t::value_type(float(255-b)/255.0f));checked.write(p);
        }
        cnn_wrapper(checked,out);assert(checked.empty() && out.size()==1);
        std::cout<<"RESULT "<<argv[file]<<' '<<std::hex<<out.read().data.range(31,0).to_uint()<<std::dec<<'\n';
    }
}
