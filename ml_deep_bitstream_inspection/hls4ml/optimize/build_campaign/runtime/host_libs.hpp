#pragma once
// Campaign extension of the frozen production CoyoteInference raw-input runtime.
// The production package and its ABI are not modified.
#include <coyote/cThread.hpp>
#include <array>
#include <cstdint>

struct TrialMeasurement {
    uint64_t signature, status, transport_bytes, trial_tag;
    uint64_t host_start_ns, submit_start_ns, submit_return_ns;
    uint64_t host_dma_done_ns, host_verdict_seen_ns;
    uint64_t csr[24]; // registers 6..29, ABI v3
};

class CoyoteInference {
public:
    CoyoteInference(unsigned backend, unsigned max_input_bytes, coyote::CoyoteAllocType allocation);
    ~CoyoteInference();
    CoyoteInference(const CoyoteInference&) = delete;
    void set_raw_data(const uint8_t* bytes, unsigned raw_len);
    void flush();
    void configure_pixel_fifo(unsigned depth);
    TrialMeasurement predict();
    void clock_sample(uint64_t* triple);
    float* get_predictions() { return dst_mem; }
private:
    unsigned backend, capacity, raw_len=0, pixel_fifo_capacity=32;
    bool prepared=false;
    uint64_t tag=0, signature=0;
    coyote::cThread coyote_thread;
    uint8_t* src_mem=nullptr;
    float* dst_mem=nullptr;
    coyote::localSg src_sg{}, dst_sg{};
};

extern "C" {
const char* campaign_last_error();
void* campaign_init(unsigned backend, unsigned max_input_bytes, unsigned allocation);
uint64_t campaign_now_ns();
int campaign_configure_fifo(void* obj, unsigned depth);
int campaign_prepare(void* obj, const uint8_t* bytes, unsigned raw_len);
int campaign_predict(void* obj, TrialMeasurement* result);
int campaign_clock(void* obj, uint64_t* triple);
int campaign_close(void* obj);
}
