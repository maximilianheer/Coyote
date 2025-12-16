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

#ifndef __FPGA_NET_H__
#define __FPGA_NET_H__

// Include the FPGA device header for device-specific structures and definitions
#include "coyote_defs.h"
#include "coyote_setup.h"
#include "vfpga_isr.h"
#include "vfpga_uisr.h"
#include "vfpga_ops.h"

// Only declare the public interfaces for registering and unregistering the FPGA network device

/**
 * fpga_net_register - Register the FPGA network device
 * @priv: pointer to the FPGA device structure (for a vFPGA)
 * 
 * Returns 0 on success, negative error code on failure
 */
int vfpga_net_register(struct vfpga_dev *vfpga, uint64_t net_mac_addr);

/**
 * fpga_net_unregister - Unregister the FPGA network device
 * @priv: pointer to the FPGA device structure (for a vFPGA)
 */
void vfpga_net_unregister(struct vfpga_dev *vfpga);

/**
 * fpga_net_irq_dispatch - Dispatch network-related IRQs
 * @vfpga: pointer to the FPGA device structure (for a vFPGA)
 */
void vfpga_net_irq_dispatch(struct vfpga_dev *vfpga);

/**
 * fpga_net_check_completed - Check if a local operation has completed
 * @vfpga: pointer to the FPGA device structure (for a vFPGA)
 * @oper: Coyote operation type
 */
uint32_t vfpga_net_check_completed(struct vfpga_dev *vfpga, CoyoteOper oper);

/**
 * fpga_net_clear_completed - Clear the writeback entry after operation completion
 * @vfpga: pointer to the FPGA device structure (for a vFPGA)
 */
void vfpga_net_clear_completed(struct vfpga_dev *vfpga);


/**
 * Definition of all the registers required for talking to the HW 
 */
typedef enum {
    HOST_NETWORKING_PID_REG = 0,            // PID process ID for the transmission
    HOST_NETWORKING_BUFF_VADDR_REG = 1,     // Virtual address of the buffer for RX
    HOST_NETWORKING_BUFF_STRIDE_REG = 2,    // Stride between two packets in the RX buffer
    HOST_NETWORKING_RING_SIZE_REG = 3,      // Size of the ring buffer in number of packets 
    HOST_NETWORKING_RING_TAIL_REG = 4,      // Tail pointer of the ring buffer (updated by FPGA)
    HOST_NETWORKING_RING_HEAD_REG = 5,      // Head pointer of the ring buffer
    HOST_NETWORKING_IRQ_COALESCE_REG = 6    // IRQ coalescing timer in microseconds
} BenchmarkRegisters;

/**
 * Definition of the datatype for metatags in the descriptor ring 
 */
typedef struct {
    uint32_t possession_flag : 1; // 1 Bit 
    uint32_t packet_len : 28;      // 28 Bits
    uint32_t rsvd : 3;            // 3 Bits, not relevant   
} meta_tag_decoded_t; 

/**
 * Function for parsing meta tags from the descriptor ring
 */
meta_tag_decoded_t decode_meta_tag(uint32_t raw);


#endif /* __FPGA_NET_H__ */