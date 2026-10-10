#include "host_libs.hpp"
uint64_t CoyoteInference::read_csr(unsigned int index) { return coyote_thread.getCSR(index); }
extern "C" {
uint64_t production_read_csr(CoyoteInference* obj,unsigned int index) { return obj->read_csr(index); }
}
