#include "mailbox.hpp"
#include <chrono>
#include <cstring>
#include <iostream>
__global__ void inspect_input(unsigned char* input,float* score,unsigned seed){
 bool ok=true;for(unsigned i=64;i<4096;i++)if(input[i]!=((i*37+seed)&255))ok=false;
 *score=ok?-1.0f:__uint_as_float(0x7fc00000U);
}
int main(){try{
 hip_check(hipSetDevice(0));GpuThread t;
 if(t.getCSR(4)!=0x4342595400030009ULL)throw std::runtime_error("D_G image required");
 auto input=(unsigned char*)t.fine_alloc(4096);auto box=(unsigned long long*)t.fine_alloc(4096);
 auto host=(unsigned char*)t.getMem({coyote::CoyoteAllocType::REG,4096});
 float* score;hip_check(hipMalloc(&score,4));
 hipEvent_t done;hip_check(hipEventCreateWithFlags(&done,hipEventReleaseToSystem|hipEventDisableTiming));
 for(unsigned trial=1;trial<=100;trial++){
  memset(host,0,4096);uint64_t n=4032;memcpy(host,&n,8);
  for(unsigned i=64;i<4096;i++)host[i]=(i*37+trial)&255;
  hip_check(hipMemset(box,0,128));hip_check(hipDeviceSynchronize());
  t.clearCompleted();t.setCSR(n,1);t.setCSR(trial,2);t.setCSR(1,0);
  coyote::localSg src={.addr=host,.len=4096,.stream=coyote::STRM_HOST,.dest=0};
  coyote::localSg dst={.addr=input,.len=4096,.stream=coyote::STRM_HOST,.dest=0};
  auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
  auto wait=[&](auto f){while(!f())if(std::chrono::steady_clock::now()>deadline){std::cerr<<"Timeout; recover FPGA before reuse\n";_Exit(3);}};
  t.invoke(coyote::CoyoteOper::LOCAL_TRANSFER,src,dst);
  wait([&]{return t.checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=1 && t.checkCompleted(coyote::CoyoteOper::LOCAL_WRITE)>=1;});
  hipLaunchKernelGGL(inspect_input,dim3(1),dim3(1),0,0,input,score,trial);
  hipLaunchKernelGGL(publish_mailbox,dim3(1),dim3(1),0,0,box,score,trial,0x43565233U);
  hip_check(hipGetLastError());hip_check(hipEventRecord(done,0));hip_check(hipEventSynchronize(done));
  coyote::localSg result={.addr=box+8,.len=64,.stream=coyote::STRM_HOST,.dest=1};
  t.invoke(coyote::CoyoteOper::LOCAL_READ,result);
  wait([&]{return t.checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=2;});wait([&]{return t.getCSR(0)&6;});
  if(t.getCSR(0)!=2 || t.getCSR(26)!=0xbf800000ULL)throw std::runtime_error("fine-grained GPU input/publication mismatch");
  if(trial%10==0)std::cout<<"PASS fine-grained input/publication trial="<<trial<<std::endl;
 }
 hip_check(hipEventDestroy(done));hip_check(hipFree(score));
 std::cout<<"PASS fine-grained DMA-BUF export, GPU reads of external writes, ordered GPU payload publication: 100 trials. Autonomous readiness polling requires new image.\n";
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
