#pragma once
#include <coyote/cThread.hpp>
#include <hip/hip_runtime.h>
#include <hsa/hsa_ext_amd.h>
#include <stdexcept>
#include <vector>
inline void hip_check(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
// Small transport adapter; upstream Coyote driver/library are unchanged.
class GpuThread:public coyote::cThread {
 struct Mapping{void* ptr;uint64_t base;int fd;};
 std::vector<Mapping> mappings;
public:
 GpuThread():coyote::cThread(0,getpid(),0){}
 void* fine_alloc(size_t size){
  void* p=nullptr;hip_check(hipExtMallocWithFlags(&p,size,hipDeviceMallocFinegrained));
  int export_fd=-1;size_t offset=0;
  if(hsa_amd_portable_export_dmabuf(p,size,&export_fd,&offset)!=HSA_STATUS_SUCCESS){hipFree(p);throw std::runtime_error("fine-grained DMA-BUF export failed");}
  uint64_t args[coyote::MAX_USER_ARGS]={};args[0]=export_fd;args[1]=uint64_t(p)-offset;args[2]=ctid;args[3]=uint64_t(-1);
  if(ioctl(fd,IOCTL_MAP_DMABUF,&args)){hsa_amd_portable_close_dmabuf(export_fd);hipFree(p);throw std::runtime_error("fine-grained DMA-BUF mapping failed");}
  mappings.push_back({p,uint64_t(p)-offset,export_fd});return p;
 }
 ~GpuThread(){
  // Caller must quiesce all DMA before destruction; timeout paths retain mappings.
  for(auto m:mappings){uint64_t args[coyote::MAX_USER_ARGS]={m.base,uint64_t(ctid)};
   if(ioctl(fd,IOCTL_UNMAP_DMABUF,&args))std::terminate();
   hsa_amd_portable_close_dmabuf(m.fd);hipFree(m.ptr);
  }
 }
};
// Separate cachelines: [0..63] readiness, [64..127] immutable payload.
// Publication is integer-only; CNN tensors use the framework's ordinary allocator.
__global__ void publish_mailbox(unsigned long long* box,const float* score,unsigned long long trial,unsigned magic){
 box[8]=(static_cast<unsigned long long>(magic)<<32)|__float_as_uint(*score);box[9]=trial;
 __threadfence_system();
 unsigned gen=unsigned(trial);
 reinterpret_cast<volatile unsigned*>(box)[1]=~gen;
 __threadfence_system();
 reinterpret_cast<volatile unsigned*>(box)[0]=gen;
 __threadfence_system();
}
