#include "firmware/prod_res256_manualA_coyote_accel.h"
#include <cassert>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
int main(int argc,char**argv) {
    assert(argc==2);std::ofstream out(argv[1]);assert(out.good());
    out<<"raw_byte,pixel_bits,logit_hex,logit\n";
    for(unsigned byte=0;byte<256;byte++) {
        hls::stream<input_t> pixels;hls::stream<result_t> result;
        input_t token;token[0]=input_t::value_type(float(255-byte)/255.0f);
        for(unsigned i=0;i<65536;i++)pixels.write(token);
        prod_res256_manualA_coyote_accel(pixels,result);
        assert(pixels.empty() && result.size()==1);
        float value=float(result.read()[0]);unsigned bits;std::memcpy(&bits,&value,4);
        out<<std::dec<<byte<<','<<token[0].range(15,0).to_uint()<<','<<std::hex<<bits<<','<<std::dec<<std::setprecision(10)<<value<<'\n';out.flush();
        std::cout<<"PASS reference byte="<<byte<<std::endl;
    }
}
