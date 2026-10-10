// CPU-host runner for the frozen direct-stream ABI v3. One context per session.
#include <coyote/cThread.hpp>
#include "direct_abi.hpp"
#include <array>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/mman.h>
#include <unistd.h>

static uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
struct Case {
    std::string id, sweep, path, hash;
    uint64_t bytes;
    uint32_t expected;
};
static std::vector<Case> read_cases(const char* path) {
    std::ifstream f(path); if(!f) throw std::runtime_error("cannot open case manifest");
    std::vector<Case> result; std::string line;
    while(std::getline(f,line)) {
        if(line.empty() || line[0]=='#')continue;
        std::istringstream row(line);std::vector<std::string> v;std::string x;
        while(std::getline(row,x,'\t'))v.push_back(x);
        if(v.size()!=6)throw std::runtime_error("manifest requires 6 TSV fields");
        Case c{v[0],v[1],v[2],v[4],std::stoull(v[3]),uint32_t(std::stoul(v[5],nullptr,16))};
        if(c.bytes>134217664ULL)throw std::runtime_error("raw input exceeds frozen hardware limit");
        result.push_back(c);
    }
    if(result.empty())throw std::runtime_error("empty case manifest");return result;
}
int main(int argc,char**argv) {
    try {
        if(argc!=7)throw std::runtime_error("usage: board_benchmark CASES.tsv TRIALS.csv CLOCK.csv VARIANT TRIALS WARMUPS");
        auto cases=read_cases(argv[1]);unsigned variant=std::stoul(argv[4]);
        unsigned trials=std::stoul(argv[5]),warmups=std::stoul(argv[6]);
        if((variant!=7 && variant!=8)||!trials||trials>100000||warmups>100000)
            throw std::runtime_error("invalid variant/trial configuration");
        std::ofstream csv(argv[2]),clock(argv[3]);
        if(!csv||!clock)throw std::runtime_error("cannot open output");
        csv<<"case_id,sweep,input_sha256,variant,input_bytes,transport_bytes,trial,trial_tag,warmup,status,signature,host_start_ns,submit_start_ns,submit_return_ns,host_dma_done_ns,host_verdict_seen_ns";
        for(unsigned reg=6;reg<=29;++reg)csv<<",csr_"<<reg;csv<<'\n';csv.flush();
        clock<<"case_id,position,host_before_ns,fpga_tick,host_after_ns\n";clock.flush();
        coyote::cThread thread(0,getpid());
        auto signature=thread.getCSR(direct::SIGNATURE);
        if(signature!=(direct::signature|variant))throw std::runtime_error("unexpected FPGA signature");
        uint64_t tag=0;
        for(const auto& c:cases) {
            std::ifstream input_file(c.path,std::ios::binary|std::ios::ate);
            if(!input_file || uint64_t(input_file.tellg())!=c.bytes)throw std::runtime_error("input size mismatch: "+c.id);
            size_t frame=64+((c.bytes+63)/64)*64;
            auto* input=static_cast<unsigned char*>(thread.getMem({coyote::CoyoteAllocType::REG,uint32_t(frame)}));
            if(!input||input==MAP_FAILED)throw std::runtime_error("host allocation failed");
            std::memset(input,0,frame);
            for(unsigned b=0;b<8;++b)input[b]=(c.bytes>>(8*b))&255;
            input_file.seekg(0);if(c.bytes)input_file.read(reinterpret_cast<char*>(input+64),c.bytes);
            if(!input_file)throw std::runtime_error("input read failed");
            thread.setCSR(c.bytes,direct::RAW_BYTES);
            auto calibrate=[&](const char* position) {
                for(unsigned j=0;j<32;++j) {
                    auto a=now_ns(),tick=thread.getCSR(direct::TICK),b=now_ns();
                    clock<<c.id<<','<<position<<','<<a<<','<<tick<<','<<b<<'\n';
                }
                clock.flush();
            };
            calibrate("before");
            coyote::localSg src={.addr=input,.len=uint32_t(frame),.stream=coyote::STRM_HOST,.dest=0};
            std::cout<<"CASE_START "<<c.id<<" bytes="<<c.bytes<<std::endl;
            for(unsigned i=0;i<warmups+trials;++i) {
                ++tag;auto start=now_ns();
                thread.clearCompleted();thread.setCSR(tag,direct::TRIAL);thread.setCSR(1,direct::STATUS);
                auto submit=now_ns();thread.invoke(coyote::CoyoteOper::LOCAL_READ,src);auto returned=now_ns();
                auto wait=[&](auto condition) {
                    while(!condition()) {
                        auto status=thread.getCSR(direct::STATUS);
                        if(status&4)throw std::runtime_error("FPGA error: "+c.id+" trial "+std::to_string(i));
                        if(now_ns()-start>30000000000ULL)throw std::runtime_error("30s timeout: "+c.id+" trial "+std::to_string(i));
                    }
                };
                wait([&]{return thread.checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=1;});auto dma_done=now_ns();
                wait([&]{return (thread.getCSR(direct::STATUS)&3)==2;});auto observed=now_ns();
                wait([&]{return (thread.getCSR(direct::EVENTS)&(1ULL<<8))!=0;});
                auto status=thread.getCSR(direct::STATUS);std::array<uint64_t,24> regs{};
                for(unsigned reg=6;reg<=29;++reg)regs[reg-6]=thread.getCSR(reg);
                csv<<c.id<<','<<c.sweep<<','<<c.hash<<','<<variant<<','<<c.bytes<<','<<frame<<','<<i<<','<<tag<<','<<(i<warmups)<<','<<status<<','<<signature<<','<<start<<','<<submit<<','<<returned<<','<<dma_done<<','<<observed;
                for(auto value:regs)csv<<','<<value;csv<<'\n';csv.flush();
                auto get=[&](unsigned reg){return regs[reg-6];};
                uint64_t required=(variant==7?0x1fcULL:0x180ULL)|(c.bytes?3:0);
                if(status!=2 || (get(direct::EVENTS)&required)!=required || get(direct::INPUT_BEATS)!=frame/64)
                    throw std::runtime_error("invalid event/count/status: "+c.id);
                if(variant==7) {
                    uint32_t bits=get(direct::RESULT);uint64_t verdict=(get(direct::RESULT)>>32)&1;
                    uint64_t expected_verdict=!(c.expected>>31)||!(c.expected&0x7fffffff);
                    if(bits!=c.expected||verdict!=expected_verdict||get(direct::PP_COUNT)!=65536||get(direct::CNN_COUNT)!=65536)
                        throw std::runtime_error("checker parity/token mismatch: "+c.id+" got="+std::to_string(bits)+" expected="+std::to_string(c.expected));
                }
            }
            calibrate("after");thread.freeMem(input);
            std::cout<<"CASE_PASS "<<c.id<<std::endl;
        }
        std::cout<<"SESSION_PASS variant="<<variant<<std::endl;
    }catch(const std::exception& e) {std::cerr<<"BENCHMARK_FAILED "<<e.what()<<std::endl;return 1;}
}
