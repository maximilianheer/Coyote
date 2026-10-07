// Usage: opt_bench INPUT OUTPUT.csv [trials=200] [warmups=20]
// Variants I/U/N/P consume raw bytes; C consumes exactly 65536 float32 values.
#include <coyote/cThread.hpp>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>
#include <unistd.h>
int main(int argc,char**argv) {
 try {
    if(argc<3 || argc>5) throw std::runtime_error("usage: opt_bench INPUT OUTPUT.csv [trials=200] [warmups=20]");
    unsigned trials=argc>3?std::stoul(argv[3]):200,warmups=argc>4?std::stoul(argv[4]):20;
    if(!trials || trials>100000 || warmups>100000) throw std::runtime_error("invalid trial count");
    std::ifstream input(argv[1],std::ios::binary);
    if(!input) throw std::runtime_error("cannot open input");
    std::vector<unsigned char> raw((std::istreambuf_iterator<char>(input)),{});
    coyote::cThread thread(0,getpid());
    auto signature=thread.getCSR(15);
    unsigned abi=(signature>>16)&0xffff;
    if((signature>>32)!=0x43425954ULL || (abi!=1 && abi!=2)) throw std::runtime_error("wrong FPGA register ABI");
    unsigned variant=signature&0xffff;
    if(variant<1 || variant>6) throw std::runtime_error("unknown variant");
    if(variant==5 && raw.size()!=65536*4) throw std::runtime_error("inference-only input must be 65536 float32 values");
    size_t bytes=variant==5?raw.size():64+((raw.size()+63)/64)*64;
    if(bytes>128*1024*1024) throw std::runtime_error("input exceeds 128 MiB transport cap");
    auto* buffer=static_cast<unsigned char*>(thread.getMem({coyote::CoyoteAllocType::REG,uint32_t(bytes)}));
    if(!buffer) throw std::runtime_error("allocation failed");
    std::memset(buffer,0,bytes);
    if(variant==5) std::memcpy(buffer,raw.data(),raw.size());
    else {
        uint64_t n=raw.size();for(unsigned b=0;b<8;b++)buffer[b]=(n>>(8*b))&255;
        if(!raw.empty())std::memcpy(buffer+64,raw.data(),raw.size());
    }
    thread.invoke(coyote::CoyoteOper::LOCAL_OFFLOAD,coyote::syncSg{buffer,bytes});
    thread.setCSR(reinterpret_cast<uint64_t>(buffer),1);
    thread.setCSR(bytes,2);thread.setCSR(thread.getCtid(),3);
    std::ofstream out(argv[2]);if(!out)throw std::runtime_error("cannot open output CSV");
    out<<"variant,input_bytes,transport_bytes,trial,warmup,host_wall_ns,request_tick,first_input_cycles,last_input_cycles,preprocess_cycles,inference_cycles,publish_cycles,input_starve_cycles,input_backpressure_cycles,input_beats,decision_cycles,result_bits,preprocess_start,inference_start,publish_start,read_ack_cycles,abi_version,event_flags,payload_first_cycles,payload_last_cycles,pp_start_cycles,pp_end_cycles,cnn_task_start_cycles,logit_cycles,produced_tokens\n";
    for(unsigned i=0;i<warmups+trials;i++) {
        auto begin=std::chrono::steady_clock::now();thread.setCSR(1,0);
        uint64_t status;
        while(!((status=thread.getCSR(0))&2) || (status&1)) {
            if(status&4)throw std::runtime_error("FPGA rejected trial");
            if(std::chrono::steady_clock::now()-begin>std::chrono::seconds(30))throw std::runtime_error("FPGA timeout");
        }
        auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-begin).count();
        out<<variant<<','<<raw.size()<<','<<bytes<<','<<i<<','<<(i<warmups)<<','<<ns;
        for(unsigned reg=4;reg<=14;reg++)out<<','<<thread.getCSR(reg);
        for(unsigned reg=16;reg<=19;reg++)out<<','<<thread.getCSR(reg);
        out<<','<<abi;
        for(unsigned reg=20;reg<=27;reg++) {
            out<<','; if(abi==2) out<<thread.getCSR(reg);
        }
        out<<'\n';out.flush();
    }
    std::cout<<"Recorded "<<trials<<" trials and "<<warmups<<" warmups; cycle counts use the implemented aclk.\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
