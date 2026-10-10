#include "host_libs.hpp"
#include "../templates/direct_abi.hpp"
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <unistd.h>

namespace {
uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
thread_local std::string last_error;
template<class F> int checked(F f) {
    try { f(); last_error.clear(); return 0; }
    catch(const std::exception& e) { last_error=e.what(); return -1; }
    catch(...) { last_error="unknown Coyote runtime error"; return -1; }
}
CoyoteInference& instance(void* obj) {
    if(!obj) throw std::runtime_error("null inference session");
    return *static_cast<CoyoteInference*>(obj);
}
}

CoyoteInference::CoyoteInference(unsigned mode, unsigned max_bytes, coyote::CoyoteAllocType allocation):
    backend(mode),capacity(max_bytes),coyote_thread(0,getpid()) {
    if((mode!=7 && mode!=8) || max_bytes>134217664)
        throw std::runtime_error("invalid direct backend or raw capacity");
    signature=coyote_thread.getCSR(direct::SIGNATURE);
    if(signature!=(direct::signature|backend)) throw std::runtime_error("unexpected FPGA signature");
    // Production raw runtime: registered input/output buffers and local scatter/gather.
    const unsigned frame=64+((max_bytes+63)/64)*64;
    src_mem=static_cast<uint8_t*>(coyote_thread.getMem({allocation,frame}));
    dst_mem=static_cast<float*>(coyote_thread.getMem({allocation,unsigned(sizeof(float))}));
    if(!src_mem || src_mem==MAP_FAILED || !dst_mem || dst_mem==MAP_FAILED)
        throw std::runtime_error("inference buffer allocation failed");
    src_sg={.addr=src_mem,.len=64,.stream=coyote::STRM_HOST,.dest=0};
    dst_sg={.addr=dst_mem,.len=sizeof(float),.stream=coyote::STRM_HOST,.dest=0};
}

CoyoteInference::~CoyoteInference() {
    // Explicit release avoids leaving allocations to cThread's destructor traversal.
    if(src_mem && src_mem!=MAP_FAILED)coyote_thread.freeMem(src_mem);
    if(dst_mem && dst_mem!=MAP_FAILED)coyote_thread.freeMem(dst_mem);
}

void CoyoteInference::set_raw_data(const uint8_t* bytes,unsigned size) {
    if(size>capacity || (size && !bytes)) throw std::runtime_error("invalid raw input");
    if(coyote_thread.getCSR(direct::STATUS)&1) throw std::runtime_error("checker is busy");
    raw_len=size;
    // Production header format, with mandatory D_I/D_N full-beat padding.
    src_sg.len=64+((size+63)/64)*64;
    std::memset(src_mem,0,64);
    uint64_t length=size;
    for(unsigned b=0;b<8;++b)src_mem[b]=(length>>(8*b))&255;
    if(size)std::memcpy(src_mem+64,bytes,size);
    std::memset(src_mem+64+size,0,src_sg.len-64-size);
    coyote_thread.setCSR(size,direct::RAW_BYTES);
    prepared=true;
}

void CoyoteInference::flush() {
    std::memset(dst_mem,0,sizeof(float));
    coyote_thread.clearCompleted();
}

TrialMeasurement CoyoteInference::predict() {
    if(!prepared) throw std::runtime_error("prepare input before predict");
    TrialMeasurement result{};
    result.signature=signature;result.transport_bytes=src_sg.len;result.trial_tag=++tag;
    result.host_start_ns=now_ns();
    if(coyote_thread.getCSR(direct::STATUS)&1) throw std::runtime_error("checker is busy");
    flush();
    coyote_thread.setCSR(tag,direct::TRIAL);
    coyote_thread.setCSR(1,direct::STATUS);
    result.submit_start_ns=now_ns();
    coyote_thread.invoke(coyote::CoyoteOper::LOCAL_READ,src_sg);
    result.submit_return_ns=now_ns();
    auto wait=[&](auto condition) {
        while(!condition()) {
            if(coyote_thread.getCSR(direct::STATUS)&4)throw std::runtime_error("FPGA error status");
            if(now_ns()-result.host_start_ns>30000000000ULL)
                throw std::runtime_error("30s timeout; stop and inspect board before retry");
        }
    };
    wait([&]{return coyote_thread.checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=1;});
    result.host_dma_done_ns=now_ns();
    wait([&]{return (coyote_thread.getCSR(direct::STATUS)&3)==2;});
    result.host_verdict_seen_ns=now_ns();
    wait([&]{return coyote_thread.getCSR(direct::EVENTS)&(1ULL<<8);});
    result.status=coyote_thread.getCSR(direct::STATUS);
    for(unsigned reg=6;reg<=29;++reg)result.csr[reg-6]=coyote_thread.getCSR(reg);
    if(coyote_thread.getCSR(direct::TRIAL)!=tag) throw std::runtime_error("trial tag changed");
    auto reg=[&](unsigned i){return result.csr[i-6];};
    uint64_t required=(backend==7?0x1fcULL:0x180ULL)|(raw_len?3:0);
    if(result.status!=2 || (reg(direct::EVENTS)&required)!=required || reg(direct::INPUT_BEATS)!=src_sg.len/64)
        throw std::runtime_error("invalid completion events or input beat count");
    if(backend==7) {
        uint32_t bits=reg(direct::RESULT);
        std::memcpy(dst_mem,&bits,sizeof(bits));
        uint64_t verdict=!(bits>>31)||!(bits&0x7fffffff);
        if(!std::isfinite(*dst_mem) || ((reg(direct::RESULT)>>32)&1)!=verdict ||
           reg(direct::PP_COUNT)!=65536 || reg(direct::CNN_COUNT)!=65536 || reg(direct::FIFO_MAX)>32)
            throw std::runtime_error("invalid verdict or pixel counts");
    } else *dst_mem=std::numeric_limits<float>::quiet_NaN();
    return result;
}

void CoyoteInference::clock_sample(uint64_t* triple) {
    triple[0]=now_ns();triple[1]=coyote_thread.getCSR(direct::TICK);triple[2]=now_ns();
}

extern "C" {
const char* campaign_last_error(){return last_error.c_str();}
void* campaign_init(unsigned backend,unsigned capacity,unsigned allocation) {
    CoyoteInference* obj=nullptr;
    checked([&]{
        if(allocation>1)throw std::runtime_error("allocation must be HPF(0) or REG(1)");
        obj=new CoyoteInference(backend,capacity,allocation?coyote::CoyoteAllocType::REG:coyote::CoyoteAllocType::HPF);
    });
    return obj;
}
int campaign_prepare(void* obj,const uint8_t* bytes,unsigned size){return checked([&]{instance(obj).set_raw_data(bytes,size);});}
int campaign_predict(void* obj,TrialMeasurement* out){return checked([&]{if(!out)throw std::runtime_error("null result");*out=instance(obj).predict();});}
int campaign_clock(void* obj,uint64_t* out){return checked([&]{if(!out)throw std::runtime_error("null clock buffer");instance(obj).clock_sample(out);});}
int campaign_close(void* obj){return checked([&]{delete static_cast<CoyoteInference*>(obj);});}
}
