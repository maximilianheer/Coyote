#ifndef DIRECT_GPU_BACKEND_HPP
#define DIRECT_GPU_BACKEND_HPP
#include <cstdint>
#include <hip/hip_runtime.h>
// Adapter contract for the ORIGINAL GPU_BASELINE implementation. The adapter
// must establish visibility of completed external DMA before reading the input.
// It writes a direct::GpuResult into result_gpu (score, magic, trial id), and
// returns only after GPU work and result publication have completed. Durations
// are measured by HIP events, never inferred from CPU enqueue times.
struct GpuStageTimes {double visibility_ms,preprocess_ms,inference_ms,publish_ms;};
struct GpuBackend {
    uint32_t abi;
    const char* provenance;
    void* (*create)(int gpu_device);
    int (*run)(void* context,const void* frame_gpu,uint64_t raw_bytes,
               void* result_gpu,uint64_t trial,GpuStageTimes* times);
    void (*destroy)(void* context);
};
// Shared-library export. No fallback CNN or fabricated score is permitted.
extern "C" const GpuBackend* coyote_gpu_baseline_backend();
#endif
