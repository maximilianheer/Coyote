// Transport/DLPack/publication only. Model inference stays in TensorFlow.
#include "mailbox.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <chrono>
#include <cstring>
#include <memory>
#include <cmath>
namespace py=pybind11;
struct DLDevice{int device_type,device_id;};
struct DLDataType{uint8_t code,bits;uint16_t lanes;};
struct DLTensor{void* data;DLDevice device;int ndim;DLDataType dtype;int64_t* shape;int64_t* strides;uint64_t byte_offset;};
struct DLManagedTensor{DLTensor dl_tensor;void* manager_ctx;void(*deleter)(DLManagedTensor*);};
static uint64_t ns(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
class Transport:public std::enable_shared_from_this<Transport>{
 GpuThread* thread=nullptr;unsigned char* host=nullptr;unsigned char* gpu=nullptr;
 unsigned long long* box=nullptr;unsigned long long* host_result=nullptr;
 hipStream_t stream=nullptr;hipEvent_t copy_begin,copy_end,pub_begin,pub_end;
 uint32_t n=0,bytes=0,capacity;uint64_t trial=0;unsigned variant;
 uint64_t start_ns=0,submit_ns=0,submitted_ns=0,input_ready_ns=0;
 bool armed=false;
 void bounded_wait(const std::function<bool()>& predicate){
  while(!predicate()){
   if(thread->getCSR(0)&4)throw std::runtime_error("FPGA error: inspect CSRs; drain/reset before reuse");
   if(ns()-start_ns>31000000000ULL)throw std::runtime_error("Trial timeout; reset hardware before releasing mappings");
  }
 }
public:
 explicit Transport(uint32_t max_bytes):capacity(max_bytes){
  if(capacity<64 || capacity>134217728 || capacity%64)throw std::runtime_error("capacity must be aligned and <=128MiB");
  hip_check(hipSetDevice(0));thread=new GpuThread();
  auto sig=thread->getCSR(4);variant=sig&65535;
  if((sig&~65535ULL)!=0x4342595400040000ULL || (variant!=10&&variant!=11)){
   delete thread;thread=nullptr;throw std::runtime_error("Requires OPT7/OPT8 GPU ABI v4 image");
  }
  gpu=(unsigned char*)thread->fine_alloc(capacity);box=(unsigned long long*)thread->fine_alloc(4096);
  // Match the FPGA production runner's huge-page DMA buffers. Regular pages
  // introduce a different Coyote TLB workload and invalidate transport comparisons.
  host=(unsigned char*)thread->getMem({coyote::CoyoteAllocType::HPF,capacity});
  host_result=(unsigned long long*)thread->getMem({coyote::CoyoteAllocType::HPF,64});
  if(!host||!host_result)throw std::runtime_error("host buffer allocation failed");
  hip_check(hipHostRegister(host,capacity,hipHostRegisterDefault));
  hip_check(hipStreamCreateWithFlags(&stream,hipStreamNonBlocking));
  hip_check(hipEventCreate(&copy_begin));hip_check(hipEventCreateWithFlags(&copy_end,hipEventReleaseToSystem));
  hip_check(hipEventCreate(&pub_begin));hip_check(hipEventCreateWithFlags(&pub_end,hipEventReleaseToSystem));
 }
 ~Transport(){
  if(!thread)return;
  if((thread->getCSR(0)&1)||thread->getCSR(37)){std::cerr<<"Live DMA: retaining buffers; hardware recovery required\n";return;}
  if(stream)hipStreamSynchronize(stream);
  hipEventDestroy(copy_begin);hipEventDestroy(copy_end);hipEventDestroy(pub_begin);hipEventDestroy(pub_end);
  hipStreamDestroy(stream);hipHostUnregister(host);delete thread;
 }
 void load(py::array_t<uint8_t,py::array::c_style> raw){
  if(armed)throw std::runtime_error("previous trial not collected");
  if(uint64_t(raw.size())>capacity-64)throw std::runtime_error("input exceeds capacity");
  n=raw.size();bytes=64+((n+63)/64)*64;
  if(uint64_t(raw.size())>capacity-64 || bytes>capacity)throw std::runtime_error("input exceeds capacity");
  memset(host,0,64);uint64_t len=n;memcpy(host,&len,8);
  if(n)memcpy(host+64,raw.data(),n);
  memset(host+64+n,0,bytes-64-n);
 }
 void start(uint64_t id){
  if(armed || !id || !(id&0xffffffffULL) || bytes==0)throw std::runtime_error("invalid trial/rearm");
  if((thread->getCSR(0)&1)||thread->getCSR(37))throw std::runtime_error("FPGA not quiescent");
  // Mailbox initialization is per-trial setup and included in the host interval.
  start_ns=ns();trial=id;
  hip_check(hipMemsetAsync(box,0,128,stream));hip_check(hipStreamSynchronize(stream));
  thread->clearCompleted();thread->setCSR(n,1);thread->setCSR(trial,2);
  thread->setCSR(uint64_t(box),32);thread->setCSR(uint64_t(box+8),33);thread->setCSR(thread->getCtid(),34);
  thread->setCSR(250,35);thread->setCSR(7500000000ULL,36);thread->setCSR(1,0);armed=true;
  coyote::localSg src={.addr=host,.len=bytes,.stream=coyote::STRM_HOST,.dest=0};
  coyote::localSg dst={.addr=gpu,.len=bytes,.stream=coyote::STRM_HOST,.dest=0};
  submit_ns=ns();
  if(variant==11)thread->invoke(coyote::CoyoteOper::LOCAL_TRANSFER,src,dst);
  else{
   hip_check(hipEventRecord(copy_begin,stream));hip_check(hipMemcpyAsync(gpu,host,bytes,hipMemcpyHostToDevice,stream));hip_check(hipEventRecord(copy_end,stream));
   thread->invoke(coyote::CoyoteOper::LOCAL_READ,src);
  }
  submitted_ns=ns();
 }
 void wait_input(){
  if(variant==10)hip_check(hipEventSynchronize(copy_end));
  else{
   bounded_wait([&]{return thread->checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=1 && thread->checkCompleted(coyote::CoyoteOper::LOCAL_WRITE)>=1;});
   // Fine-grained input avoids a coarse-grained GPU cache handoff; dispatch is
   // after the DMA observation. Exact external-write visibility admission is required.
   hip_check(hipDeviceSynchronize());
  }
  input_ready_ns=ns();
 }
 py::capsule input_capsule(){
  if(!armed)throw std::runtime_error("trial not started");
  auto* tensor=new DLManagedTensor{};tensor->dl_tensor={gpu+64,{10,0},1,{1,8,1},new int64_t[1]{n},nullptr,0};
  tensor->manager_ctx=new std::shared_ptr<Transport>(shared_from_this());
  tensor->deleter=[](DLManagedTensor* t){delete[] t->dl_tensor.shape;delete static_cast<std::shared_ptr<Transport>*>(t->manager_ctx);delete t;};
  return py::capsule(tensor,"dltensor",[](PyObject* p){if(PyCapsule_IsValid(p,"dltensor")){auto* t=static_cast<DLManagedTensor*>(PyCapsule_GetPointer(p,"dltensor"));t->deleter(t);}});
 }
 void publish_gpu(py::capsule capsule){
  if(variant!=11)throw std::runtime_error("GPU publication only for P2P");
  auto* t=static_cast<DLManagedTensor*>(PyCapsule_GetPointer(capsule.ptr(),"dltensor"));
  if(!t)throw py::error_already_set();
  auto& d=t->dl_tensor;uint64_t elements=1;for(int i=0;i<d.ndim;i++)elements*=d.shape[i];
  if(d.device.device_type!=10 || d.device.device_id!=0 || d.dtype.code!=2 || d.dtype.bits!=32 || d.dtype.lanes!=1 || elements!=1)throw std::runtime_error("requires scalar FP32 ROCm tensor");
  // TensorFlow to_dlpack establishes producer completion; do not infer its cost from HIP events.
  hip_check(hipEventRecord(pub_begin,stream));
  hipLaunchKernelGGL(publish_mailbox,dim3(1),dim3(1),0,stream,box,reinterpret_cast<const float*>(static_cast<const char*>(d.data)+d.byte_offset),trial,0x43565234U);
  hip_check(hipGetLastError());hip_check(hipEventRecord(pub_end,stream));hip_check(hipEventSynchronize(pub_end));
  PyCapsule_SetName(capsule.ptr(),"used_dltensor");if(t->deleter)t->deleter(t);
 }
 void publish_host(float score){
  if(variant!=10 || !std::isfinite(score))throw std::runtime_error("invalid host result");
  memset(host_result,0,64);uint32_t bits;memcpy(&bits,&score,4);
  host_result[0]=(0x43565234ULL<<32)|bits;host_result[1]=trial;
  coyote::localSg src={.addr=host_result,.len=64,.stream=coyote::STRM_HOST,.dest=1};
  thread->invoke(coyote::CoyoteOper::LOCAL_READ,src);
 }
 py::dict finish(){
  bounded_wait([&]{return (thread->getCSR(0)&3)==2;});auto observed=ns();
  bounded_wait([&]{return !thread->getCSR(37) && thread->checkCompleted(coyote::CoyoteOper::LOCAL_READ)>=(variant==10?2:1) && (variant==10 || thread->checkCompleted(coyote::CoyoteOper::LOCAL_WRITE)>=1);});
  py::dict out;out["variant"]=variant;out["trial"]=trial;out["input_bytes"]=n;out["transport_bytes"]=bytes;
  out["host_start_ns"]=start_ns;out["submit_ns"]=submit_ns;out["submitted_ns"]=submitted_ns;out["input_ready_ns"]=input_ready_ns;out["verdict_seen_ns"]=observed;
  for(unsigned i=0;i<=46;i++)out[py::str("csr_"+std::to_string(i))]=thread->getCSR(i);
  float elapsed=0;
  if(variant==10){hip_check(hipEventElapsedTime(&elapsed,copy_begin,copy_end));out["host_to_gpu_ms"]=elapsed;}
  else{hip_check(hipEventElapsedTime(&elapsed,pub_begin,pub_end));out["gpu_publication_ms"]=elapsed;}
  armed=false;return out;
 }
 py::list calibrate(){py::list out;for(int i=0;i<32;i++){auto a=ns();auto tick=thread->getCSR(5);auto b=ns();out.append(py::make_tuple(a,tick,b));}return out;}
};

// Hardware-independent admission of DLPack and the exact publication helper.
static py::capsule diagnostic_input(py::array_t<uint8_t,py::array::c_style> raw){
 hip_check(hipSetDevice(0));void* p=nullptr;
 hip_check(hipExtMallocWithFlags(&p,std::max<size_t>(raw.size(),1),hipDeviceMallocFinegrained));
 if(raw.size())hip_check(hipMemcpy(p,raw.data(),raw.size(),hipMemcpyHostToDevice));
 auto* t=new DLManagedTensor{};t->dl_tensor={p,{10,0},1,{1,8,1},new int64_t[1]{raw.size()},nullptr,0};
 t->deleter=[](DLManagedTensor* t){hipFree(t->dl_tensor.data);delete[] t->dl_tensor.shape;delete t;};
 return py::capsule(t,"dltensor",[](PyObject* p){if(PyCapsule_IsValid(p,"dltensor")){auto* t=static_cast<DLManagedTensor*>(PyCapsule_GetPointer(p,"dltensor"));t->deleter(t);}});
}
static py::tuple diagnostic_publish(py::capsule capsule,uint64_t trial){
 auto* t=static_cast<DLManagedTensor*>(PyCapsule_GetPointer(capsule.ptr(),"dltensor"));if(!t)throw py::error_already_set();
 auto& d=t->dl_tensor;uint64_t elements=1;for(int i=0;i<d.ndim;i++)elements*=d.shape[i];
 if(d.device.device_type!=10 || d.device.device_id!=0 || d.dtype.code!=2 || d.dtype.bits!=32 || d.dtype.lanes!=1 || elements!=1)throw std::runtime_error("FP32 ROCm scalar required");
 unsigned long long* box;hip_check(hipExtMallocWithFlags(reinterpret_cast<void**>(&box),4096,hipDeviceMallocFinegrained));
 hipLaunchKernelGGL(publish_mailbox,dim3(1),dim3(1),0,0,box,reinterpret_cast<const float*>(static_cast<const char*>(d.data)+d.byte_offset),trial,0x43565234U);
 hip_check(hipGetLastError());hip_check(hipDeviceSynchronize());
 unsigned long long values[16];hip_check(hipMemcpy(values,box,128,hipMemcpyDeviceToHost));hip_check(hipFree(box));
 PyCapsule_SetName(capsule.ptr(),"used_dltensor");if(t->deleter)t->deleter(t);
 return py::make_tuple(values[0],values[8],values[9]);
}
PYBIND11_MODULE(gpu_transport,m){
 m.def("diagnostic_input",&diagnostic_input);m.def("diagnostic_publish",&diagnostic_publish);
 py::class_<Transport,std::shared_ptr<Transport>>(m,"Transport")
  .def(py::init<uint32_t>(),py::arg("capacity")=134217728)
  .def("load",&Transport::load).def("start",&Transport::start)
  .def("wait_input",&Transport::wait_input,py::call_guard<py::gil_scoped_release>())
  .def("input_capsule",&Transport::input_capsule).def("publish_gpu",&Transport::publish_gpu)
  .def("publish_host",&Transport::publish_host).def("finish",&Transport::finish).def("calibrate",&Transport::calibrate);
}
