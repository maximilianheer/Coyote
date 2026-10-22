// Existing ABI-v3 D_G transport proof. No model or fabricated benchmark result.
#include <coyote/cThread.hpp>
#include <hip/hip_runtime.h>
#include <chrono>
#include <cstring>
#include <iostream>
#include <vector>
#include <thread>
#include <stdexcept>
#include <unistd.h>
static void hipcheck(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
__global__ void publish(unsigned long long* p,unsigned long long trial){
    p[0]=0x43565233bf800000ULL;p[1]=trial;__threadfence_system();
}
int main(int argc,char**argv){try{
 hipcheck(hipSetDevice(0));coyote::cThread t(0,getpid());
 if(t.getCSR(4)!=0x4342595400030009ULL)throw std::runtime_error("D_G ABI mismatch");
 auto* host=(unsigned char*)t.getMem({coyote::CoyoteAllocType::REG,134217728});
 auto* gpu=(unsigned char*)t.getMem({coyote::CoyoteAllocType::GPU,134217728,false,0});
 auto* result=(unsigned long long*)t.getMem({coyote::CoyoteAllocType::GPU,4096,false,0});
 if(!host||!gpu||!result)throw std::runtime_error("allocation failed");
 std::vector<unsigned char> check(134217728);
 unsigned trial=0;
 for(unsigned n: {0U,1U,65U,65536U,1048576U,16777216U,134217664U}){
  auto bytes=64+((n+63)/64)*64;
  memset(host,0,bytes);memcpy(host,&n,4);
  for(unsigned j=64;j<bytes;j++)host[j]=(j*37+trial*11)&255;
  for(unsigned rep=0;rep<3;rep++){
   ++trial;hipcheck(hipMemset(gpu,0xa5,bytes));hipcheck(hipDeviceSynchronize());
   t.clearCompleted();t.setCSR(n,1);t.setCSR(trial,2);t.setCSR(1,0);
   coyote::localSg src={.addr=host,.len=bytes,.stream=coyote::STRM_HOST,.dest=0};
   coyote::localSg dst={.addr=gpu,.len=bytes,.stream=coyote::STRM_HOST,.dest=0};
   auto started=std::chrono::steady_clock::now();
   auto wait=[&](auto f){while(!f()){if(std::chrono::steady_clock::now()-started>std::chrono::seconds(10)){std::cerr<<"DMA timeout; stop/recover FPGA before reusing mappings\n";_Exit(3);}}};
   t.invoke(coyote::CoyoteOper::LOCAL_TRANSFER,src,dst);
   wait([&]{return t.checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=1&&t.checkCompleted(coyote::CoyoteOper::LOCAL_WRITE)>=1;});
   hipcheck(hipMemcpy(check.data(),gpu,bytes,hipMemcpyDeviceToHost));
   if(memcmp(host,check.data(),bytes))throw std::runtime_error("FPGA->GPU byte mismatch");
   hipLaunchKernelGGL(publish,dim3(1),dim3(1),0,0,result,trial);hipcheck(hipGetLastError());hipcheck(hipDeviceSynchronize());
   coyote::localSg verdict={.addr=result,.len=64,.stream=coyote::STRM_HOST,.dest=1};
   t.invoke(coyote::CoyoteOper::LOCAL_READ,verdict);
   wait([&]{return t.checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=2;});
   wait([&]{return t.getCSR(0)&6;});
   if(t.getCSR(0)!=2||t.getCSR(26)!=0xbf800000ULL)throw std::runtime_error("GPU->FPGA verdict mismatch");
   std::cout<<"PASS bytes="<<bytes<<" trial="<<trial<<std::endl;
  }
 }
 std::cout<<"PASS P2P bidirectional: 21 frames, GPU-published verdicts, 64 B through 128 MiB transport\n";
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
