/**
  * Copyright (c) 2021, Systems Group, ETH Zurich
  * All rights reserved.
  *
  * Redistribution and use in source and binary forms, with or without modification,
  * are permitted provided that the following conditions are met:
  *
  * 1. Redistributions of source code must retain the above copyright notice,
  * this list of conditions and the following disclaimer.
  * 2. Redistributions in binary form must reproduce the above copyright notice,
  * this list of conditions and the following disclaimer in the documentation
  * and/or other materials provided with the distribution.
  * 3. Neither the name of the copyright holder nor the names of its contributors
  * may be used to endorse or promote products derived from this software
  * without specific prior written permission.
  *
  * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
  * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
  * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
  * IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
  * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
  * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
  * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
  * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
  * EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
  */

#ifndef COYOTE_RDMA_ABI_H   // <--- Add this at the very top
#define COYOTE_RDMA_ABI_H   // <--- Add this
#include <linux/types.h>

// ==============
// Structures used for communication between the RDMA core and the userspace library
// ==============

// Response structure for for ibv_create_cq
struct cyt_rdma_create_cq_resp {
    uint32_t cqn; 
    uint32_t entries; 
}; 

// Response structure for allocating user context 
struct cyt_rdma_alloc_ucontext_resp {
    // Maximum number of QPs supported by the FPGA-RDMA device
    uint32_t max_qp;

    // Maximum number of CQs supported by the FPGA-RDMA device 
    uint32_t max_cq;

    // Needs to communicate all the memory regions that we need for RDMA operations 
    uint64_t vfpga_ctrl_reg; 
    uint64_t vfpga_cnfg_reg;
    uint64_t vfpga_wb_reg;
}; 

struct cyt_rdma_alloc_pd_resp {
    uint32_t pdn; 
};

struct cyt_rdma_reg_mr_resp {
    uint32_t lkey; 
    uint32_t rkey; 
};

struct cyt_rdma_create_cq_req {
    uint32_t cqn; 
};

struct cyt_rdma_create_qp_cmd {
    uint32_t qpn; 
};

#endif // COYOTE_RDMA_ABI_H 