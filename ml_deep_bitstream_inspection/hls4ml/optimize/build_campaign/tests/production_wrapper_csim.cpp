#include "model_wrapper.hpp"
#include <algorithm>
#include <cassert>
#include <fstream>
#include <iostream>
#include <sstream>
#include <vector>

static unsigned run(const std::vector<unsigned char>& raw) {
    hls::stream<axi_s> in,out;
    auto feed=[&](hls::stream<axi_s>& stream) {
        axi_s h;h.data=raw.size();h.keep=-1;h.strb=0;h.last=raw.empty();stream.write(h);
        for(size_t i=0;i<raw.size();i+=64) {
            axi_s p;p.data=0;p.keep=0;p.strb=0;p.last=i+64>=raw.size();
            for(size_t j=0;j<64 && i+j<raw.size();j++){p.data.range(8*j+7,8*j)=raw[i+j];p.keep[j]=1;}
            stream.write(p);
        }
    };
    // Independently verify production preprocessing against integer linspace.
    feed(in);hls::stream<input_t> pixels;
    zero_in_raw::raw_bitstream_downsample_to_input_stream(in,pixels);
    assert(in.empty() && pixels.size()==65536);
    for(size_t i=0;i<65536;i++) {
        size_t idx=raw.size()>65536?i*(raw.size()-1)/65535:i;
        unsigned b=idx<raw.size()?raw[idx]:0;
        assert(pixels.read()[0]==input_t::value_type(float(255-b)/255.0f));
    }
    feed(in);
    model_wrapper(in,out);
    assert(in.empty() && out.size()==1);
    // Frozen converter writes LAST=0 for one float and leaves KEEP unspecified.
    // Production DMA is length-driven (four-byte destination descriptor).
    axi_s score=out.read();assert(score.last==0);
    return score.data.range(31,0).to_uint();
}
int main(int argc,char** argv) {
    assert(argc==3);
    std::ifstream cases(argv[1]);assert(cases.good());
    std::vector<std::vector<std::string>> rows;std::string line;
    while(std::getline(cases,line)) {
        std::stringstream ss(line);std::vector<std::string> row;std::string field;
        while(std::getline(ss,field,'\t'))row.push_back(field);
        assert(row.size()==6);rows.push_back(row);
    }
    assert(rows.size()==26);
    for(int repeat=0;repeat<2;repeat++) {
        if(repeat)std::reverse(rows.begin(),rows.end());
        for(const auto& row:rows) {
            std::ifstream file(row[2],std::ios::binary);assert(file.good());
            std::vector<unsigned char> raw((std::istreambuf_iterator<char>(file)),{});
            assert(raw.size()==std::stoull(row[3]));
            unsigned got=run(raw),expected=std::stoul(row[5],nullptr,16);
            if(got!=expected){std::cerr<<"FAIL "<<row[0]<<" got="<<std::hex<<got<<" expected="<<expected<<std::endl;return 1;}
            std::cout<<"PASS "<<row[0]<<" repeat="<<repeat<<std::endl;
        }
    }
    std::ifstream reference(argv[2]);assert(reference.good());
    std::ofstream rtl("rtl_expected.txt");size_t n;unsigned golden;unsigned count=0;
    while(reference>>std::dec>>n>>std::hex>>golden) {
        if(n==64 || n==4194240 || n==4194242)continue;
        std::vector<unsigned char> raw(n);
        for(size_t i=0;i<n;i++)raw[i]=(i*131+i/11+17)&255;
        unsigned got=run(raw);assert(got==golden);
        rtl<<std::dec<<n<<' '<<std::hex<<golden<<'\n';count++;
    }
    assert(count==8);std::cout<<"PASS production framing/pixels/logits: 52 corpus calls + 8 RTL references"<<std::endl;
}
