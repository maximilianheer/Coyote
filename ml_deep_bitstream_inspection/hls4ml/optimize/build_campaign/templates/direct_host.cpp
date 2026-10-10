// Deferred board runner. No board operation occurs during compilation/build.
#include <coyote/cThread.hpp>
#include "direct_abi.hpp"
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>
#include <unistd.h>
#ifdef DIRECT_GPU
#include "gpu_backend.hpp"
#include <dlfcn.h>
#endif
static uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
int main(int argc,char** argv) {
    try {
        if(argc<3 || argc>7)throw std::runtime_error("usage: direct_bench INPUT OUTPUT.csv [trials=200] [warmups=20] [GPU_BACKEND.so] [gpu_id=0]");
        unsigned trials=argc>3?std::stoul(argv[3]):200,warmups=argc>4?std::stoul(argv[4]):20;
        if(!trials || trials>100000 || warmups>100000)throw std::runtime_error("invalid trial count");
        std::ifstream f(argv[1],std::ios::binary);if(!f)throw std::runtime_error("cannot open input");
        std::vector<unsigned char> raw((std::istreambuf_iterator<char>(f)),{});
        size_t bytes=64+((raw.size()+63)/64)*64;
        if(bytes>128*1024*1024)throw std::runtime_error("frame exceeds 128 MiB");
        coyote::cThread thread(0,getpid());
        auto signature=thread.getCSR(direct::SIGNATURE);
        if((signature&~0xffffULL)!=direct::signature)throw std::runtime_error("wrong direct-stream ABI");
        unsigned variant=signature&0xffff;
        if(variant<7 || variant>9)throw std::runtime_error("wrong variant");
        void* gpu_input=nullptr;void* gpu_result=nullptr;
#ifdef DIRECT_GPU
        void* library=nullptr;const GpuBackend* backend=nullptr;void* context=nullptr;
        int gpu_id=argc>6?std::stoi(argv[6]):0;
        if(variant==9) {
            if(argc<6)throw std::runtime_error("GPU baseline adapter required; no substitute model is used");
            if(hipSetDevice(gpu_id)!=hipSuccess)throw std::runtime_error("cannot select GPU");
            library=dlopen(argv[5],RTLD_NOW|RTLD_LOCAL);if(!library)throw std::runtime_error(dlerror());
            auto get=reinterpret_cast<const GpuBackend*(*)()>(dlsym(library,"coyote_gpu_baseline_backend"));
            if(!get || !(backend=get()) || backend->abi!=1 || !backend->create || !backend->run || !backend->destroy || !backend->provenance)
                throw std::runtime_error("invalid GPU baseline adapter ABI");
            context=backend->create(gpu_id);if(!context)throw std::runtime_error("GPU backend initialization failed");
            std::cout<<"GPU backend provenance: "<<backend->provenance<<'\n';
            gpu_input=thread.getMem({coyote::CoyoteAllocType::GPU,uint32_t(bytes),false,uint32_t(gpu_id)});
            gpu_result=thread.getMem({coyote::CoyoteAllocType::GPU,64,false,uint32_t(gpu_id)});
            if(!gpu_input || !gpu_result)throw std::runtime_error("GPU DMA-BUF allocation failed");
        }
#else
        if(variant==9)throw std::runtime_error("GPU runner requires DIRECT_GPU=ON and original baseline adapter");
#endif
        auto* input=static_cast<unsigned char*>(thread.getMem({coyote::CoyoteAllocType::REG,uint32_t(bytes)}));
        if(!input)throw std::runtime_error("host allocation failed");
        std::memset(input,0,bytes);
        for(unsigned b=0;b<8;b++)input[b]=(uint64_t(raw.size())>>(8*b))&255;
        if(!raw.empty())std::memcpy(input+64,raw.data(),raw.size());
        thread.setCSR(raw.size(),direct::RAW_BYTES);
        coyote::localSg src={.addr=input,.len=uint32_t(bytes),.stream=coyote::STRM_HOST,.dest=0};
        coyote::localSg dst={.addr=gpu_input,.len=uint32_t(bytes),.stream=coyote::STRM_HOST,.dest=0};
        coyote::localSg result_src={.addr=gpu_result,.len=64,.stream=coyote::STRM_HOST,.dest=1};
        std::ofstream csv(argv[2]);std::ofstream calibration(std::string(argv[2])+".clock.csv");
        if(!csv || !calibration)throw std::runtime_error("cannot open output");
        calibration<<"position,host_before_ns,fpga_tick,host_after_ns\n";
        auto calibrate=[&](const char* position) {
            for(unsigned j=0;j<32;++j) {
                auto a=now_ns();auto ticks=thread.getCSR(direct::TICK);auto b=now_ns();
                calibration<<position<<','<<a<<','<<ticks<<','<<b<<'\n';
            }
            calibration.flush();
        };
        csv<<"variant,input_bytes,transport_bytes,trial,warmup,host_start_ns,submit_start_ns,submit_return_ns,host_dma_done_ns,host_verdict_seen_ns,gpu_visibility_ms,gpu_preprocess_ms,gpu_inference_ms,gpu_publish_ms";
        for(unsigned reg=6;reg<=29;++reg)csv<<",csr_"<<reg;csv<<'\n';
        calibrate("before");
        for(unsigned i=0;i<trials+warmups;++i) {
            auto start=now_ns();
            thread.clearCompleted();thread.setCSR(i+1,direct::TRIAL);thread.setCSR(1,direct::STATUS);
            auto submit=now_ns();
            if(variant==9)thread.invoke(coyote::CoyoteOper::LOCAL_TRANSFER,src,dst);
            else thread.invoke(coyote::CoyoteOper::LOCAL_READ,src);
            auto submitted=now_ns();
            auto wait=[&](auto condition) {
                while(!condition()) {
                    if(thread.getCSR(direct::STATUS)&4)throw std::runtime_error("FPGA rejected frame/result");
                    if(now_ns()-start>30000000000ULL)throw std::runtime_error("trial timeout; do not reuse an incomplete frame");
                }
            };
            wait([&] {return thread.checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=1 &&
                (variant!=9 || thread.checkCompleted(coyote::CoyoteOper::LOCAL_WRITE)>=1);});
            auto dma_done=now_ns();
            double visibility=0,preprocess=0,inference=0,publish=0;
#ifdef DIRECT_GPU
            if(variant==9) {
                GpuStageTimes times{};
                if(backend->run(context,gpu_input,raw.size(),gpu_result,i+1,&times))throw std::runtime_error("GPU baseline or external-DMA visibility check failed");
                visibility=times.visibility_ms;preprocess=times.preprocess_ms;inference=times.inference_ms;publish=times.publish_ms;
                thread.invoke(coyote::CoyoteOper::LOCAL_READ,result_src);
            }
#endif
            wait([&] {return (thread.getCSR(direct::STATUS)&3)==2;});
            auto observed=now_ns();
            if(variant==9)wait([&] {return thread.checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=2;});
            if(thread.getCSR(direct::STATUS)&4)throw std::runtime_error("invalid completed trial");
            csv<<variant<<','<<raw.size()<<','<<bytes<<','<<i<<','<<(i<warmups)<<','<<start<<','<<submit<<','<<submitted<<','<<dma_done<<','<<observed
                <<','<<visibility<<','<<preprocess<<','<<inference<<','<<publish;
            for(unsigned reg=6;reg<=29;++reg)csv<<','<<thread.getCSR(reg);csv<<'\n';csv.flush();
        }
        calibrate("after");
#ifdef DIRECT_GPU
        if(context)backend->destroy(context);
        if(library)dlclose(library);
#endif
        std::cout<<"Trials complete; FPGA ticks require implemented clock and bracketed host alignment.\n";
    }catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
