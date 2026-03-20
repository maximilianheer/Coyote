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

#include "vfpga_net.h"
#include <linux/swab.h>
#include <asm/unaligned.h>
#include <net/gso.h>

// ======-------------------------------------------------------------------------------
//
// FPGA network functions - Exposes Coyote as a proper NIC to the system 
//
// ======-------------------------------------------------------------------------------

// Global variable for the ctid used by the FPGA-NIC 
int32_t vfpga_net_ctid = -1;

// Constant definitions for variables declared in coyote_defs.h
const unsigned long STRM_CARD = 0;
const unsigned long STRM_HOST = 1;
const unsigned long STRM_RDMA = 2;
const unsigned long STRM_TCP = 3;
const int CMD_FIFO_DEPTH = 32;
const int CMD_FIFO_THR = 10;
const unsigned long MAX_TRANSFER_SIZE = 128 * 1024 * 1024;
const long SLEEP_TIME = 100L;

/**
 * fpga_rx_has_packet - Check if there is a new packet in the RX ring buffer
 * @vfpga: pointer to the FPGA device structure (for a vFPGA)
 */
static bool vfpga_rx_has_packet(struct vfpga_dev *vfpga);

/**
 * fpga_rx_fetch_packet - Fetch a packet from the RX ring buffer
 * @vfpga: pointer to the FPGA device structure (for a vFPGA)
 */
static struct sk_buff *vfpga_rx_fetch_packet(struct vfpga_dev *vfpga);

// Helper function to post an operation for the vFPGA handling the arbitrary traffic 
static void vfpga_net_post_command(struct vfpga_dev *vfpga, uint64_t offs_3, uint64_t offs_2, uint64_t offs_1, uint64_t offs_0) {

    // Step 1: Check the outstanding commands to not oversaturate the FPGA queues 
    /* dbg_info("vfpga_net_post_command: Current command count before posting new command: %llu\n", vfpga->cmd_cnt);
    while(vfpga->cmd_cnt > CMD_FIFO_DEPTH - CMD_FIFO_THR) {
        //dbg_info("vfpga_net_post_command: Command count %llu exceeds threshold %d, rechecking...\n", vfpga->cmd_cnt, CMD_FIFO_DEPTH - CMD_FIFO_THR);
        // Recheck the command count by reading back the FPGA register
        vfpga->cmd_cnt = (uint32_t)(vfpga->vfpga_net_cnfg[CTRL_REG] & 0xFFFFFFFF); 
        //dbg_info("vfpga_net_post_command: Updated command count after rechecking: %llu\n", vfpga->cmd_cnt);

        // If the command count is still too high, sleep for a short time to avoid busy-waiting
        if(vfpga->cmd_cnt > (CMD_FIFO_DEPTH - CMD_FIFO_THR)) {
            //dbg_info("vfpga_net_post_command: Command count %llu still exceeds threshold %d, sleeping briefly...\n", vfpga->cmd_cnt, CMD_FIFO_DEPTH - CMD_FIFO_THR);
            // std::this_thread::sleep_for(std::chrono::nanoseconds(SLEEP_TIME));
            udelay(1); 
        }
    } */ 

    // Step 1: Post the command to the FPGA
    //dbg_info("vfpga_net_post_command: Posting command with offsets: %llx, %llx, %llx, %llx\n", offs_3, offs_2, offs_1, offs_0);
    // Base index for the control registers for the FPGA-NIC
    vfpga->vfpga_net_cnfg[CTRL_REG + 1] = offs_1;
    vfpga->vfpga_net_cnfg[CTRL_REG + 2] = offs_2;
    vfpga->vfpga_net_cnfg[CTRL_REG + 3] = offs_3;
    vfpga->vfpga_net_cnfg[CTRL_REG + 0] = offs_0;


    // Step 2: Check if the command has been processed by the FPGA
    //dbg_info("vfpga_net_post_command: Verifying command posting...\n");
    // vfpga->cmd_cnt = (uint32_t)(vfpga->vfpga_net_cnfg[CTRL_REG] & 0xFFFFFFFFUL);
    //dbg_info("vfpga_net_post_command: Command count after posting command: %llu\n", vfpga->cmd_cnt);
    // if(vfpga->cmd_cnt > 0) {
        //dbg_info("That's not great, but what should we do now anyways? Packet's lost, another one will come in the future... \n");
    // }
    /* while(vfpga->cmd_cnt > 0) {
        //dbg_info("vfpga_net_post_command: Command count is non zero, waiting for FPGA to process command...\n");
        // Recheck the command count by reading back the FPGA register
        vfpga->cmd_cnt = (uint32_t)(vfpga->vfpga_net_cnfg[CTRL_REG] & 0xFFFFFFFF);
        // std::this_thread::sleep_for(std::chrono::nanoseconds(SLEEP_TIME));
        udelay(10); 
    } */ 
}

// Helper function for local operations to the vFPGA handling the arbitrary traffic 
static int vfpga_net_invoke_local_op(struct vfpga_dev *vfpga, CoyoteOper oper, struct localSg sg, bool last) {
    //dbg_info("vfpga_net_invoke_local_op: Invoking local operation of type %d\n", (int)(oper));

    // Step 1: Check if the specified operation is supported in the current setting and if the buffer is not too long
    if (!isLocalRead(oper) && !isLocalWrite(oper)) {
        //dbg_info("vfpga_net_invoke_local_op: Unsupported operation type %d for local operation\n", (int)(oper));
        return -EINVAL;
    }

    if (sg.len > MAX_TRANSFER_SIZE) {
        //dbg_info("vfpga_net_invoke_local_op: Transfer size %u exceeds maximum supported size %lu\n", sg.len, MAX_TRANSFER_SIZE);
        return -EINVAL;
    }

    // Step 2: Dissect the meta-information to create the required arguments for calling the post_command function
    uint64_t ctrl_cmd_src = 0;
    uint64_t ctrl_cmd_dst = 0;
    uint64_t addr_cmd_src = 0;
    uint64_t addr_cmd_dst = 0;

    //dbg_info("vfpga_net_invoke_local_op: Preparing command parameters \n");

    if(oper == LOCAL_READ) {
        //dbg_info("vfpga_net_invoke_local_op: Preparing LOCAL_READ command with parameters: ctid %d, dest %u, last %d, stream %u, len %u \n",
        //    vfpga_net_ctid, sg.dest, last ? 1 : 0, sg.stream, sg.len);
        ctrl_cmd_src = ((vfpga_net_ctid & CTRL_PID_MASK) << CTRL_PID_OFFS) |
                ((sg.dest & CTRL_DEST_MASK) << CTRL_DEST_OFFS) |
                (last ? CTRL_LAST : 0x0) |
                ((sg.stream & CTRL_STRM_MASK) << CTRL_STRM_OFFS) |
                (CTRL_START) |
                (0x0) |
                ((uint64_t)(sg.len) << CTRL_LEN_OFFS);
        //dbg_info("vfpga_net_invoke_local_op: Computed ctrl_cmd_src: %llx \n", ctrl_cmd_src);

        addr_cmd_src = (uint64_t)(sg.addr);

        //dbg_info("vfpga_net_invoke_local_op: Posting LOCAL_READ command with parameters: addr_cmd_dst %llx, ctrl_cmd_dst %llx, addr_cmd_src %llx, ctrl_cmd_src %llx \n", addr_cmd_dst, ctrl_cmd_dst, addr_cmd_src, ctrl_cmd_src);
        vfpga_net_post_command(vfpga, addr_cmd_dst, ctrl_cmd_dst, addr_cmd_src, ctrl_cmd_src);
        //dbg_info("vfpga_net_invoke_local_op: LOCAL_READ command posted successfully\n");

    } else if(oper == LOCAL_WRITE) {
        ctrl_cmd_dst = ((vfpga_net_ctid & CTRL_PID_MASK) << CTRL_PID_OFFS) |
            ((sg.dest & CTRL_DEST_MASK) << CTRL_DEST_OFFS) |
            (last ? CTRL_LAST : 0x0) |
            ((sg.stream & CTRL_STRM_MASK) << CTRL_STRM_OFFS) |
            (CTRL_START) |
            (0x0) |
            ((uint64_t)(sg.len) << CTRL_LEN_OFFS);

        addr_cmd_dst = (uint64_t)(sg.addr);

        vfpga_net_post_command(vfpga, addr_cmd_dst, ctrl_cmd_dst, addr_cmd_src, ctrl_cmd_src);
        //dbg_info("vfpga_net_invoke_local_op: LOCAL_WRITE command posted successfully\n");
    } else {
        //dbg_info("vfpga_net_invoke_local_op: Unsupported operation type %d for local operation\n", (int)(oper));
        return -EINVAL;
    }

    // Writeback reclaim is handled exclusively by the caller (vfpga_net_xmit /
    // vfpga_net_poll) so that completions are never lost to a double-clear.
    return 0;
}

// Function for polling the writeback region to check for operation completion 
uint32_t vfpga_net_check_completed(struct vfpga_dev *vfpga, CoyoteOper oper) {
    // Based on operation type, check the corresponding writeback entry
    if(isLocalWrite(oper)) {
        //dbg_info("vfpga_net_check_completed: Checking completion for LOCAL_WRITE operation\n");
        return vfpga->vfpga_net_wb[vfpga_net_ctid + WR_WBACK * N_CTID_MAX];
    } else if(isLocalRead(oper)) {
        //dbg_info("vfpga_net_check_completed: Checking completion for LOCAL_READ operation\n");
        return vfpga->vfpga_net_wb[vfpga_net_ctid + RD_WBACK * N_CTID_MAX];
    } else {
        //dbg_info("vfpga_net_check_completed: Unsupported operation type %d for checking completion\n", (int)(oper));
        return 0;
    }
}

// Function for clearing the writeback entry after operation completion
void vfpga_net_clear_completed(struct vfpga_dev *vfpga) {
    //dbg_info("vfpga_net_clear_completed: Clearing writeback entry for ctid %d\n", vfpga_net_ctid);
    vfpga->vfpga_net_wb[vfpga_net_ctid + RD_WBACK * N_CTID_MAX] = 0;
    vfpga->vfpga_net_wb[vfpga_net_ctid + WR_WBACK * N_CTID_MAX] = 0;
}

// Function for opening the new FPGA-NIC
static int vfpga_net_open(struct net_device *dev)
{
    struct vfpga_dev *vfpga = *(struct vfpga_dev **)netdev_priv(dev);

    // Initialize the TX lock and start the queue 
    spin_lock_init(&vfpga->tx_lock);

    //dbg_info("vfpga_net_open at the beginning: NAPI struct address: %p\n", &vfpga->napi);
    //dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    //dbg_info("napi.poll=%p\n", vfpga->napi.poll);

    // Buffer allocation for the vFPGA, using ioremap for kernelspace mapping 
    
    // Control-mmap 
    //dbg_info("Trying to allocate net ctrl memory at %llx of size %d.\n", vfpga->vfpga_cnfg_phys_addr+VFPGA_CTRL_USER_OFFS, VFPGA_CTRL_USER_SIZE); 
    vfpga->vfpga_net_ctrl = ioremap((vfpga->vfpga_cnfg_phys_addr + VFPGA_CTRL_USER_OFFS), VFPGA_CTRL_USER_SIZE); 
    if(vfpga->vfpga_net_ctrl == NULL) {
        //dbg_info("Couldn't allocate control memory.");
        return -ENOMEM; 
    } else {
        //dbg_info("Successfully allocated the net ctrl memory at %llx.\n", *vfpga->vfpga_net_ctrl);
    }

    // Config-mmap -> Used for giving commands to the FPGA 
    //dbg_info("Trying to allocate net cnfg memory at %llx of size %d.\n", vfpga->vfpga_cnfg_avx_phys_addr, VFPGA_CTRL_CNFG_AVX_SIZE); 
    vfpga->vfpga_net_cnfg = ioremap(vfpga->vfpga_cnfg_avx_phys_addr, VFPGA_CTRL_CNFG_AVX_SIZE); 
    if(vfpga->vfpga_net_cnfg == NULL) {
        //dbg_info("Couldn't allocate config memory."); 
        return -ENOMEM; 
    } else {
        //dbg_info("Successfully allocated the net cnfg memory at %llx. \n", *vfpga->vfpga_net_cnfg);
    }

    // Writeback buffer is host RAM (dma_alloc_coherent); use wb_addr_virt directly
    // instead of ioremap, which would create an uncached MMIO mapping and turn
    // every completion read into a slow PCIe round-trip.
    vfpga->vfpga_net_wb = (volatile uint64_t *)vfpga->wb_addr_virt;

    // Also, reset the current counter of outstanding commands to the FPGA to later be able to work efficiently with this command pipeline 
    vfpga->cmd_cnt = 0;

    // Config-mmap 
    /* dbg_info("Trying to allocate net cnfg memory at %llx of size %lx.\n", vfpga->vfpga_cnfg_avx_phys_addr, VFPGA_CTRL_CNFG_AVX_SIZE); 
    vfpga->vfpga_net_cnfg = ioremap(vfpga->vfpga_cnfg_avx_phys_addr, VFPGA_CTRL_CNFG_AVX_SIZE); 
    if(vfpga->vfpga_net_cnfg == NULL) {
        //dbg_info("Couldn't allocate config memory."); 
        return -ENOMEM; 
    } else {
        //dbg_info("Successfully allocated the net cnfg memory. \n"); 
    }

    // Writeback-mmap
    //dbg_info("Trying to allocate writeback memory at %llx of size %lx. \n", vfpga->wb_phys_addr, WB_SIZE);
    vfpga->vfpga_net_wb = ioremap(vfpga->wb_phys_addr, WB_SIZE);
    if(vfpga->vfpga_net_wb == NULL) {
        //dbg_info("Couldn't allocate writeback memory."); 
        return -ENOMEM; 
    } else {
        //dbg_info("Successfully allocated the net writeback memory. \n"); 
    } */ 

    // Allocate the RX- and TX-buffer for packet transmission 
    //dbg_info("Trying to allocate the RX-buffer for arbitrary packet reception. \n"); 

    if (!vfpga) {
        //dbg_info("VFPGA CRASH: vfpga is NULL!\n");
        return -ENOMEM; // Or handle the error gracefully
    }

    // 1. Check bd_data
    if (!vfpga->bd_data) {
        //dbg_info("VFPGA CRASH: bd_data is NULL.\n");
        return -ENOMEM;
    }

    // 2. Check pci_dev
    if (!vfpga->bd_data->pci_dev) {
        //dbg_info("VFPGA CRASH: pci_dev is NULL.\n");
        return -ENOMEM;
    }

    // 3. Check the internal 'dev' pointer (the struct device)
    /* if (vfpga->bd_data->pci_dev->dev == NULL) {
        //dbg_info("VFPGA CRASH: struct device reference is NULL.\n");
        return -ENOMEM;
    } */ 

    //dbg_info("Printing the RX Buf physical address %llx \n", vfpga->vfpga_net_rx_buf_phys_addr);

    // Call ioctl for registering the ctid. We assume a fixed hpid of 17 for the NIC. 
    //dbg_info("Trying to register a ctid for the FPGA-NIC. \n"); 

    // Pass on the hpid 17 for the NIC as arg to the ioctl call 
    uint64_t tmp_reg_ctid[32];
    tmp_reg_ctid[0] = current->pid;

    // Print the current pid 
    //dbg_info("Current process pid is %d \n", current->pid);

    if(vfpga_dev_ioctl_functionality(vfpga, IOCTL_REGISTER_CTID, (uint64_t)&tmp_reg_ctid, true) < 0 ) {
        //dbg_info("Couldn't register a ctid for the FPGA-NIC. \n"); 
        return -ENOMEM; 
    } else {
        // On success, read back the allocated ctid from the arg array
        vfpga_net_ctid = tmp_reg_ctid[1];  
        //dbg_info("Successfully registered ctid %d for the FPGA-NIC. \n", vfpga_net_ctid); 
    }

    //dbg_info("Trying to allocate the RX-buffer for arbitrary packet reception. \n"); 
    vfpga->vfpga_net_rx_buf = dma_alloc_coherent(&vfpga->bd_data->pci_dev->dev, RX_BUFF_SIZE, &vfpga->vfpga_net_rx_buf_phys_addr, GFP_KERNEL);
    if(!vfpga->vfpga_net_rx_buf) {
        //dbg_info("Couldn't allocate the RX-buffer for the net-device. \n"); 
        return -ENOMEM; 
    } else {
        //dbg_info("Successfully allocated the RX-buffer for the net-device at %llx. \n", *vfpga->vfpga_net_rx_buf); 
    }

    //dbg_info("Trying to allocate the TX-buffer for arbitrary packet reception. \n"); 
    vfpga->vfpga_net_tx_buf = dma_alloc_coherent(&vfpga->bd_data->pci_dev->dev, TX_BUFF_SIZE, &vfpga->vfpga_net_tx_buf_phys_addr, GFP_KERNEL);
    if(!vfpga->vfpga_net_tx_buf) {
        //dbg_info("Couldn't allocate the TX-buffer for the net-device. \n");
        return -ENOMEM;
    } else {
        //dbg_info("Successfully allocated the TX-buffer for the net-device at %llx. \n", *vfpga->vfpga_net_tx_buf);
    }

    // Initialise TX ring indices
    vfpga->tx_head      = 0;
    vfpga->tx_completed = 0;

    // Add both the TX- and RX-buffers to the kernel buffer map for the given ctid
    //dbg_info("Adding the RX-buffer to the kernel buffer map for ctid %d. \n", vfpga_net_ctid);
    tlb_get_kernel_buffers(vfpga, (uint64_t)(((uint64_t)vfpga->vfpga_net_rx_buf & 0xFFFFFFFFFFFFULL) >> 12), vfpga->vfpga_net_rx_buf_phys_addr, vfpga_net_ctid, RX_BUFF_SIZE);
    //dbg_info("Adding the TX-buffer to the kernel buffer map for ctid %d. \n", vfpga_net_ctid);
    tlb_get_kernel_buffers(vfpga, (uint64_t)(((uint64_t)vfpga->vfpga_net_tx_buf & 0xFFFFFFFFFFFFULL) >> 12), vfpga->vfpga_net_tx_buf_phys_addr, vfpga_net_ctid, TX_BUFF_SIZE);
    //dbg_info("Successfully added both RX- and TX-buffers to the kernel buffer map for ctid %d. \n", vfpga_net_ctid);

    // -----------------------
    // AXI-CTRL to the vFPGA 
    // -----------------------

    // ssleep(1);

    // Offset 0: HOST_NETWORKING_PID
    //dbg_info("Write host-pid 0 to ctrl-reg. \n");
    writeq(vfpga_net_ctid, vfpga->vfpga_net_ctrl + 0);
    // iowrite64(0, vfpga->vfpga_net_rx_buf + 1); 
    // vfpga->vfpga_net_rx_buf[1] = 0; 

    // Offset 1: RX_BUFF_VADDR
    //dbg_info("Write RX-buffer address %llx to ctrl-reg. \n", *vfpga->vfpga_net_rx_buf);
    writeq((uint64_t)vfpga->vfpga_net_rx_buf, vfpga->vfpga_net_ctrl + 1);
    // iowrite64(vfpga->vfpga_net_rx_buf, vfpga->vfpga_net_rx_buf); 
    // vfpga->vfpga_net_rx_buf[0] = vfpga->vfpga_net_rx_buf; 

    // Offset 2: HOST_NETWORKING_BUFF_STRIDE 
    //dbg_info("Write buff_stride 6144 to ctrl-reg. \n");
    writeq(6144, vfpga->vfpga_net_ctrl + 2);
    // iowrite64(6144, vfpga->vfpga_net_rx_buf + 2); 
    // vfpga->vfpga_net_rx_buf[2] = 6144; 

    // Offset 3: HOST_NETWORKING_RING_SIZE
    //dbg_info("Write ring_size 512 to ctrl-reg. \n");
    writeq(512, vfpga->vfpga_net_ctrl + 3);
    // iowrite64(512, vfpga->vfpga_net_rx_buf + 3); 
    // vfpga->vfpga_net_rx_buf[3] = 512; 

    // Offset 4: HOST_NETWORKING_RING_HEAD 
    //dbg_info("Write ring head 0 to ctrl-reg. \n");
    writeq(0, vfpga->vfpga_net_ctrl + 4);
    // vfpga->vfpga_net_rx_buf[4] = 0; 
    // iowrite64(0, vfpga->vfpga_net_rx_buf + 4); 


    // Offset 5: HOST_NETWORKING_IRQ_COALESCE
    //dbg_info("Write irq coalesce 16 to ctrl-reg. \n");
    writeq(64, vfpga->vfpga_net_ctrl + 6);
    // vfpga->vfpga_net_rx_buf[5] = 16; 
    // iowrite64(16, vfpga->vfpga_net_rx_buf + 5); 


    pr_info("vfpga_net: device %s opened\n", dev->name);

    // Enable the NAPI polling for the FPGA-NIC
    //dbg_info("Enabling NAPI polling for the FPGA-NIC. \n");
    BUG_ON(!vfpga->ndev);
    BUG_ON(!&vfpga->napi);

    // Preflight Check #1: Check that ndev is valid and not null 
    if(!vfpga->ndev) {
        //dbg_info("vfpga_net_open: vfpga->ndev is NULL!\n");
        return -ENOMEM; // Or handle the error gracefully
    }

    // Preflight Check #2: Print the contents of the napi struct to ensure it exists
    //dbg_info("vfpga_net_open at the end: NAPI struct address: %p\n", &vfpga->napi);
    //dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    //dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    // struct napi_struct *napi = &vfpga->napi;
    napi_enable(&vfpga->napi);
    netif_start_queue(dev);

    // Tell the kernel the physical link is up
    netif_carrier_on(dev);
    //dbg_info("vfpga_net_open: Set the network carrier on for the FPGA-NIC. \n");
    //dbg_info("Successfully started the netif queue for the FPGA-NIC. \n");

    // Poll the status of the interface in the driver 
    if(netif_carrier_ok(dev)) {
        //dbg_info("vfpga_net_open: Network carrier is OK for device %s. \n", dev->name);
    } else {
        //dbg_info("vfpga_net_open: Network carrier is NOT OK for device %s. \n", dev->name);
    }

    return 0;
}

// Function for stopping the FPGA-NIC 
static int vfpga_net_stop(struct net_device *dev)
{
    struct vfpga_dev *vfpga = *(struct vfpga_dev **)netdev_priv(dev);

    // Stop the queue 
    netif_stop_queue(dev);

    // Set the link state to OFF 
    netif_carrier_off(dev);
    //dbg_info("vfpga_net_stop: Set the network carrier off for the FPGA-NIC. \n");

    // Set the RX-Buf addr in the hardware to 0 to stop HW-functionality 
    //dbg_info("Write RX-buffer address 0 to ctrl-reg. \n");
    writeq(0, vfpga->vfpga_net_ctrl + 0);


    // Buffer deallocation for the vFPGA, using ioremap for kernelspace mapping 
    //dbg_info("Trying to deallocate the buffers held for ctrl, cnfg and wb of the vFPGA. \n"); 
    iounmap(vfpga->vfpga_net_ctrl); 
    // iounmap(vfpga->vfpga_net_cnfg); 
    // iounmap(vfpga->vfpga_net_wb); 
    //dbg_info("Successfully deallocated the buffers held for ctrl, cnfg and wb of the vFPGA. \n"); 

    // Deallocating the RX- and TX-buffer for the net-device 
    //dbg_info("Trying to deallocate the RX- and TX buffers held for the net vFPGA. \n"); 
    // dma_free_coherent(&vfpga->bd_data->pci_dev->dev, RX_BUFF_SIZE, vfpga->vfpga_net_rx_buf, &vfpga->vfpga_net_rx_buf_phys_addr); 
    // dma_free_coherent(&vfpga->bd_data->pci_dev->dev, TX_BUFF_SIZE, vfpga->vfpga_net_tx_buf, &vfpga->vfpga_net_tx_buf_phys_addr); 
    //dbg_info("Successfully deallocated the RX- and TX-buffers held for the net vFPGA. \n"); 


    // Stopping of the hardware etc. 

    pr_info("vfpga_net: device %s closed\n", dev->name);
    return 0;
}

// Function that is called when the FPGA issues an interrupt for packet reception at threshold 
void vfpga_net_irq_dispatch(struct vfpga_dev *vfpga)
{
    //dbg_info("Dispatching NAPI poll for FPGA-NIC \n");
    //dbg_info("vfpga_net_irq_dispatch: NAPI struct address: %p\n", &vfpga->napi);
    //dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    //dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    // napi_enable(&vfpga->napi);
    napi_schedule(&vfpga->napi);
}

// Function that polls the RX-ring buffer for new packets and handles their processing within the Linux network stack 
static int vfpga_net_poll(struct napi_struct *napi, int budget)
{
    //dbg_info("vfpga_net_poll: Polling the RX-ring buffer for new packets from the FPGA-NIC. \n");
    // return 0;

    // Get the vfpga device structure from the napi struct
    struct vfpga_dev *vfpga = container_of(napi, struct vfpga_dev, napi);
    //dbg_info("vfpga_net_poll: Retrieved vfpga device structure. \n");

    // Count the number of packets processed (must not exceed the budget given during registration)
    int packets_processed = 0;

    //dbg_info("vfpga_net_poll: Starting packet processing loop with budget %d. \n", budget);

    while(packets_processed < budget && vfpga_rx_has_packet(vfpga)) {
        //dbg_info("vfpga_net_poll: Processing packet %d. \n", packets_processed + 1);

        // Fetch the packet from the RX-ring buffer
        struct sk_buff *skb = vfpga_rx_fetch_packet(vfpga);

        if(!skb) {
            //dbg_info("vfpga_net_poll: Didn't get the skb back from the RX-ring (although there should have been one...) \n");
            break;
        }

        // Pass the packet to the network stack
        //dbg_info("vfpga_net_poll: Passing the packet to the network stack. \n");
        // skb->protocol = eth_type_trans(skb, vfpga->ndev);
        napi_gro_receive(napi, skb);
        //dbg_info("vfpga_net_poll: Packet successfully passed to the network stack. \n");

        packets_processed++;
        //dbg_info("vfpga_net_poll: Finished processing packet %d. \n", packets_processed);
    }

    // Checking if we processed all packets or if we reached the budget limit
    if(packets_processed < budget) {
        // Check if there are no more packets left in the RX-ring buffer
        if(!vfpga_rx_has_packet(vfpga)) {
            //dbg_info("vfpga_net_poll: No more packets left in RX-ring buffer, completing NAPI poll. \n");
            napi_complete_done(napi, packets_processed);
        }
    }

    // Write the updated consumer pointer back to the FPGA hardware so that the
    // edge-triggered IRQ threshold can re-arm for the next incoming packet.
    // Without this, (write_ptr - ring_head_reg) never drops back below the
    // coalesce threshold and no further RX interrupts are generated.
    if (packets_processed > 0)
        writeq(vfpga->rx_buf_head, vfpga->vfpga_net_ctrl + 4);

    // Reclaim any TX completions that arrived while we were polling RX, and
    // restart the TX queue if it was stopped due to a full ring.
    spin_lock(&vfpga->tx_lock);
    //dbg_info("vfpga_net_poll: Checking for completed TX operations to reclaim slots. \n");
    uint32_t tx_done = vfpga_net_check_completed(vfpga, LOCAL_READ);
    if (tx_done > vfpga->tx_completed) {
        //dbg_info("vfpga_net_poll: Found %u completed TX operations to reclaim. \n", tx_done - vfpga->tx_completed);
        vfpga->tx_completed = tx_done;
        // vfpga_net_clear_completed(vfpga);
        //dbg_info("vfpga_net_poll: Reclaimed %u TX slots in poll, tx_completed=%u tx_head=%u. \n",
        //         tx_done, vfpga->tx_completed, vfpga->tx_head);
        if (netif_queue_stopped(vfpga->ndev) &&
            (vfpga->tx_head - vfpga->tx_completed) < TX_NUM_SLOTS)
            netif_wake_queue(vfpga->ndev);
    }
    spin_unlock(&vfpga->tx_lock);

    //dbg_info("vfpga_net_poll: Finished polling with %d packets processed. \n", packets_processed);
    return packets_processed;
}

// Function to check if there is a packet available in the RX-ring buffer at the next position 
static bool vfpga_rx_has_packet(struct vfpga_dev *vfpga)
{
    // Calculate pointer to the meta word of the current RX slot
    uint8_t *base_ptr = (uint8_t *)vfpga->vfpga_net_rx_buf;
    uint8_t *pkt_ptr = base_ptr + vfpga->rx_buf_head * 6144;
    uint32_t *meta_word_ptr = (uint32_t *)(pkt_ptr);

    //dbg_info("vfpga_rx_has_packet: Base Pointer is %px\n", base_ptr);
    //dbg_info("vfpga_rx_has_packet: Packet Pointer is %px\n", pkt_ptr);
    //dbg_info("vfpga_rx_has_packet: Meta Word Pointer is %px\n", meta_word_ptr);

    // Read raw meta word from DMA buffer
    uint32_t raw_meta = *meta_word_ptr;

    // Decode the meta word
    meta_tag_decoded_t meta;
    meta.possession_flag = (raw_meta >> 31) & 0x1;
    meta.packet_len      = (raw_meta >> 3)  & 0x0FFFFFFF;
    meta.rsvd            = raw_meta & 0x7;

    //dbg_info("vfpga_rx_has_packet: Raw meta word is %08x\n", raw_meta);
    //dbg_info("vfpga_rx_has_packet: Decoded packet length: %u\n", meta.packet_len);
    //dbg_info("vfpga_rx_has_packet: Checking RX slot %d, possession_flag=%u\n",
    //         vfpga->rx_buf_head, meta.possession_flag);

    // Return true if FPGA owns the packet (flag=1)
    return (meta.possession_flag == 1);
}  

// Function to fetch the packet from the RX-ring buffer at the current position and hand it over to the network stack 
static struct sk_buff *vfpga_rx_fetch_packet(struct vfpga_dev *vfpga)
{
    // Calculate pointer to the packet of the current RX slot
    uint8_t *base_ptr = (uint8_t *)vfpga->vfpga_net_rx_buf;
    uint8_t *pkt_ptr = base_ptr + vfpga->rx_buf_head * 6144;
    uint32_t *meta_word_ptr = (uint32_t *)(pkt_ptr);

    //dbg_info("vfpga_rx_fetch_packet: Base Pointer is %px\n", base_ptr);
    //dbg_info("vfpga_rx_fetch_packet: Packet Pointer is %px\n", pkt_ptr);
    //dbg_info("vfpga_rx_fetch_packet: Meta Pointer is %px\n", meta_word_ptr);

    // Read raw meta word from DMA buffer
    uint32_t raw_meta = *meta_word_ptr;

    // Decode the meta word
    meta_tag_decoded_t meta;
    meta.possession_flag = (raw_meta >> 31) & 0x1;
    meta.packet_len      = (raw_meta >> 3)  & 0x0FFFFFFF;
    meta.rsvd            = raw_meta & 0x7;
    // One more check to ensure the possession flag is set
    if(meta.possession_flag == 0) {
        //dbg_info("vfpga_rx_fetch_packet: Possession flag not set, no packet to fetch. \n");
        return NULL;
    }

    // For fetching the actual packet: Read out the packet length from the meta-tag and calculate the packet start address
    size_t pkt_len = meta.packet_len;
    //dbg_info("vfpga_rx_fetch_packet: Packet length from meta-tag is %zu. \n", pkt_len);
    void *actual_pkt_addr = (void *)(meta_word_ptr + 1);
    //dbg_info("vfpga_rx_fetch_packet: Actual packet length is %zu, starting at address %px\n", pkt_len, actual_pkt_addr);

    // Allocate a new skb for the packet
    struct sk_buff *skb = netdev_alloc_skb(vfpga->ndev, pkt_len);
    if(!skb) {
        //dbg_info("vfpga_rx_fetch_packet: Failed to allocate skb for incoming packet. \n");
        return NULL;
    }
    //dbg_info("vfpga_rx_fetch_packet: Successfully allocated skb at %px \n", skb);
    //dbg_info("vfpga_rx_fetch_packet: alloc_skb -> skb=%p skb->data=%p skb->truesize=%u users=%d skb->dev=%p\n",
    //    skb, skb->data, skb->truesize, refcount_read(&skb->users), skb->dev);

    //if (skb->dev) {
    //    dbg_info("skb->dev: name=%s registered=%d\n", skb->dev->name,
    //            skb->dev->reg_state == NETREG_REGISTERED);
    //}

    // Copy the packet data into the skb
    dma_sync_single_for_cpu(&vfpga->bd_data->pci_dev->dev,
                        vfpga->vfpga_net_rx_buf_phys_addr +
                        (vfpga->rx_buf_head * 6144) + sizeof(uint32_t),
                        pkt_len, DMA_FROM_DEVICE);
    memcpy(skb_put(skb, pkt_len), actual_pkt_addr, pkt_len);

    // Update the stats for incoming packets and bytes
    vfpga->ndev->stats.rx_packets++;
    vfpga->ndev->stats.rx_bytes += pkt_len;

    /* char dump[512];
    char *p = dump;
    p += scnprintf(p, sizeof(dump) - (p - dump),
                "vfpga_rx_fetch_packet: Packet data (%zu bytes): ", pkt_len);

    for (size_t i = 0; i < pkt_len && (p - dump) < sizeof(dump) - 5; i++) {
        p += scnprintf(p, sizeof(dump) - (p - dump), "%02x ", ((uint8_t*)actual_pkt_addr)[i]);
    }
    //dbg_info("%s\n", dump);
    //dbg_info("\n"); */

    skb->protocol = eth_type_trans(skb, vfpga->ndev);
    skb->ip_summed = CHECKSUM_UNNECESSARY; // Hand over checksum checking to the network stack
    //dbg_info("vfpga_rx_fetch_packet: Set skb protocol to %x. \n", skb->protocol);

    // Hand over the packet to the stack
    // napi_gro_receive(&vfpga->napi, skb);
    // dev_kfree_skb_any(skb); // For testing purposes, we just free the skb here
    //dbg_info("vfpga_rx_fetch_packet: Handed over skb to the network stack. \n");

    // Clear the possession flag in the meta-tag to indicate the packet has been processed
    meta.possession_flag = 0;
    raw_meta = (meta.possession_flag << 31) |
                    ((meta.packet_len & 0x0FFFFFFF) << 3) |
                    (meta.rsvd & 0x7);
    *(uint32_t *)meta_word_ptr = raw_meta;

    wmb();
    //dbg_info("vfpga_rx_fetch_packet: Cleared possession flag in meta-tag. \n");

    // Update the RX buffer head to the next position (wrap around if necessary)
    vfpga->rx_buf_head = (vfpga->rx_buf_head + 1) % 512;
    //dbg_info("vfpga_rx_fetch_packet: Updated RX buffer head to %d. \n", vfpga->rx_buf_head);

    return skb;
}

// Function for transmitting packets
static netdev_tx_t vfpga_net_xmit(struct sk_buff *skb, struct net_device *dev)
{
    struct vfpga_dev *vfpga = *(struct vfpga_dev **)netdev_priv(dev);
    unsigned long flags;

    /* Software GSO: the kernel segmented a large flow into MTU-sized skbs
     * before calling us, but if for any reason a GSO skb still arrives here
     * (e.g. forwarded traffic), segment it now so every sub-skb fits in one
     * TX slot. */
    if (skb_is_gso(skb)) {
        struct sk_buff *segs = skb_gso_segment(skb, dev->features & ~NETIF_F_GSO);
        dev_kfree_skb(skb);
        if (IS_ERR(segs))
            return NETDEV_TX_OK;
        struct sk_buff *next;
        for (skb = segs; skb; skb = next) {
            next = skb->next;
            skb_mark_not_on_list(skb);
            vfpga_net_xmit(skb, dev);
        }
        return NETDEV_TX_OK;
    }

    size_t pkt_len = skb->len;

    //dbg_info("vfpga_net_xmit: Transmitting packet of length %zu. \n", pkt_len);

    if (pkt_len == 0 || pkt_len > BUFFER_STRIDE) {
        dev_kfree_skb_any(skb);
        dev->stats.tx_dropped++;
        //dbg_info("vfpga_net_xmit: Packet length %zu is invalid, dropping packet. \n", pkt_len);
        return NETDEV_TX_OK;
    }

    spin_lock_irqsave(&vfpga->tx_lock, flags);

    // Reclaim completed TX slots: the writeback counter tells us how many
    // LOCAL_READ ops the FPGA has finished since we last cleared it.
    uint32_t done = vfpga_net_check_completed(vfpga, LOCAL_READ);
    if (done > vfpga->tx_completed) {
        // vfpga_net_clear_completed(vfpga);
        /* dbg_info("vfpga_net_xmit: Reclaimed %u TX slots, tx_completed=%u tx_head=%u. \n",
                 done - vfpga->tx_completed, vfpga->tx_completed, vfpga->tx_head); */ 
        vfpga->tx_completed = done;
    }

    // Ring full? Stop the queue; NAPI poll will restart it once slots free up.
    if ((vfpga->tx_head - vfpga->tx_completed) >= TX_NUM_SLOTS) {
        netif_stop_queue(dev);
        spin_unlock_irqrestore(&vfpga->tx_lock, flags);
        //dbg_info("vfpga_net_xmit: TX ring full, stopping queue. \n");
        return NETDEV_TX_BUSY;
    }

    // Copy the packet into the next free slot.
    uint32_t slot = vfpga->tx_head % TX_NUM_SLOTS;
    uint8_t *slot_ptr = (uint8_t *)vfpga->vfpga_net_tx_buf + (size_t)slot * BUFFER_STRIDE;
    memcpy(slot_ptr, skb->data, pkt_len);
    //dbg_info("vfpga_net_xmit: Copied packet to TX slot %u at %px. \n", slot, slot_ptr);
    wmb();

    // Trigger the LOCAL_READ for this slot.
    struct localSg sg = LOCAL_SG_INIT;
    sg.addr   = slot_ptr;
    sg.stream = 1;
    sg.dest   = 0;
    sg.len    = pkt_len;
    vfpga_net_invoke_local_op(vfpga, LOCAL_READ, sg, true);
    //dbg_info("vfpga_net_xmit: Posted LOCAL_READ for TX slot %u. \n", slot);

    vfpga->tx_head++;

    spin_unlock_irqrestore(&vfpga->tx_lock, flags);

    dev->stats.tx_packets++;
    dev->stats.tx_bytes += pkt_len;
    dev_kfree_skb(skb);
    return NETDEV_TX_OK;
}

// Function for passing over the statistics of the FPGA-NIC 
static void vfpga_net_get_stats64(struct net_device *dev,
                           struct rtnl_link_stats64 *stats)
{
    // Copy the stats from the net_device structure to the provided stats structure
    stats->rx_packets = dev->stats.rx_packets;
    stats->tx_packets = dev->stats.tx_packets;
    stats->rx_bytes   = dev->stats.rx_bytes;
    stats->tx_bytes   = dev->stats.tx_bytes;
    stats->rx_errors  = dev->stats.rx_errors;
    stats->tx_errors  = dev->stats.tx_errors;
    stats->rx_dropped = dev->stats.rx_dropped;
    stats->tx_dropped = dev->stats.tx_dropped;

    //dbg_info("vfpga_net_get_stats64: Retrieved statistics for FPGA-NIC. \n");
}

// Function to get driver info for ethtool
static void vfpga_net_get_drvinfo(struct net_device *dev,
                          struct ethtool_drvinfo *info)
{
    strscpy(info->driver, "scenic_driver", sizeof(info->driver));
    strscpy(info->version, "0.1", sizeof(info->version));
    strscpy(info->bus_info, "PCIe", sizeof(info->bus_info));
    //dbg_info("vfpga_net_get_drvinfo: Retrieved driver info for FPGA-NIC. \n");
}

// Function to get link status for ethtool 
static u32 vfpga_net_get_link(struct net_device *dev)
{
    return netif_carrier_ok(dev); 
    //dbg_info("vfpga_net_get_link: Retrieved link status for FPGA-NIC. \n");
}

// Function to get link ksettings for ethtool
// These are obviously all faked for demonstration purposes
static int vfpga_net_get_link_ksettings(struct net_device *dev,
                               struct ethtool_link_ksettings *cmd)
{
    // ethtool_link_ksettings_add_link_mode(cmd, supported, 1000baseT_Full);
    ethtool_link_ksettings_add_link_mode(cmd, supported, Autoneg);
    ethtool_link_ksettings_add_link_mode(cmd, supported, 100000baseCR4_Full);

    cmd->base.speed = SPEED_100000;
    cmd->base.duplex = DUPLEX_FULL;
    cmd->base.autoneg = AUTONEG_ENABLE;
    cmd->base.port = PORT_FIBRE;
    //dbg_info("vfpga_net_get_link_ksettings: Retrieved link ksettings for FPGA-NIC. \n");
    return 0;
}


// Struct that points to all the functions of the FPGA-NIC in the driver 
static const struct net_device_ops vfpga_netdev_ops = {
    .ndo_open = vfpga_net_open,
    .ndo_stop = vfpga_net_stop,
    .ndo_start_xmit = vfpga_net_xmit,
    .ndo_get_stats64 = vfpga_net_get_stats64
}; 

// Struct that points to all the ethtool functions of the FPGA-NIC in the driver 
static const struct ethtool_ops vfpga_ethtool_ops = {
    .get_drvinfo = vfpga_net_get_drvinfo, 
    .get_link = vfpga_net_get_link, 
    .get_link_ksettings = vfpga_net_get_link_ksettings
};

// --------------------------------------------
// Public API for registering the new FPGA-NIC
// --------------------------------------------

// Register the FPGA-NIC
int vfpga_net_register(struct vfpga_dev *vfpga, uint64_t net_mac_addr)
{
    //dbg_info("Registering FPGA-NIC - START\n");
    int ret_val;

    // Allocate the net device structure
    //dbg_info("Trying to allocate the ethernet device\n");
    vfpga->ndev = alloc_netdev(sizeof(struct vfpga_dev *), "scenic_%d",
                          NET_NAME_UNKNOWN, ether_setup);
    if (!vfpga->ndev) {
        pr_err("fpga_net: could not allocate net device\n");
        return -ENOMEM;
    }

    vfpga->ndev->max_mtu = 4000;

    /* Enable GRO (receive) and software GSO (transmit).  The hardware cannot
     * do segmentation itself, so NETIF_F_GSO makes the kernel's GSO layer
     * split large TCP flows into MTU-sized skbs before they reach xmit. */
    vfpga->ndev->features    |= NETIF_F_GRO | NETIF_F_RXCSUM | NETIF_F_GSO | NETIF_F_SG;
    vfpga->ndev->hw_features  = vfpga->ndev->features;
    vfpga->ndev->gso_max_size = vfpga->ndev->max_mtu;
    vfpga->ndev->gso_max_segs = 65535;

    //dbg_info("Finished allocating the ethernet device\n");

    // Set the device operations
    vfpga->ndev->netdev_ops = &vfpga_netdev_ops;

    // Set the ethtool operations 
    vfpga->ndev->ethtool_ops = &vfpga_ethtool_ops;

    // Set the MAC address (for simplicity, using a fixed MAC address here)
    uint8_t mac_bytes[ETH_ALEN];
    for (int i = 0; i < ETH_ALEN; i++){
        mac_bytes[i] = (net_mac_addr >> (8 * (ETH_ALEN - 1 - i))) & 0xFF;
        //dbg_info("MAC byte %d: %02x\n", i, mac_bytes[i]);
    }

    vfpga->ndev->addr_len = ETH_ALEN; 
    if(is_valid_ether_addr(mac_bytes)) {
        //dbg_info("Assigned the correct mac_addr for the FPGA. \n");
        // ether_addr_copy(vfpga->ndev->dev_addr, mac_bytes); 
        // ether_addr_copy(vfpga->ndev->perm_addr, mac_bytes);
        eth_hw_addr_set(vfpga->ndev, mac_bytes);
    } else {
        //dbg_info("Assigned a random mac_addr for the FPGA. \n");
        eth_hw_addr_random(vfpga->ndev); // Random MAC address for demonstration
    }

    // Bind the NAPI-poll function during registration 
    //dbg_info("vfpga_net_register before manually adding: NAPI struct address: %p\n", &vfpga->napi);
    //dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    //dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    vfpga->napi.dev = vfpga->ndev;
    vfpga->napi.poll = vfpga_net_poll;
    //dbg_info("vfpga_net_register after manually adding: NAPI struct address: %p\n", &vfpga->napi);
    //dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    //dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    netif_napi_add(vfpga->ndev, &vfpga->napi, vfpga_net_poll);
    //dbg_info("vfpga_net_register after netif_napi_add: NAPI struct address: %p\n", &vfpga->napi);
    //dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    //dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    pr_info("After netif_napi_add: napi.dev=%p napi.poll=%p \n",
        vfpga->napi.dev, vfpga->napi.poll);
    //dbg_info("Finished binding NAPI poll function\n");

    // Register the network device
    //dbg_info("Actively setting the state to OFF first before turning it on later on. \n");
    netif_carrier_off(vfpga->ndev);
    //dbg_info("Trying to register the network device\n");
    ret_val = register_netdev(vfpga->ndev);
    if (ret_val) {
        pr_err("fpga_net: could not register net device\n");
        free_netdev(vfpga->ndev);
        return ret_val;
    }
    //dbg_info("Finished registering the network device\n");

    pr_info("fpga_net: device %s registered with MAC %pM\n", vfpga->ndev->name, vfpga->ndev->dev_addr);

    // struct vfpga_dev *priv = netdev_priv(vfpga->ndev);
    struct vfpga_dev **priv_ptr = netdev_priv(vfpga->ndev);
    *priv_ptr = vfpga;

    //dbg_info("vfpga_net_register after putting rebound pointer: NAPI struct address: %p\n", &vfpga->napi);
    //dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    //dbg_info("napi.poll=%p\n", vfpga->napi.poll);

    // Printing the napi stored in priv of ndev
    struct vfpga_dev *check_priv = *(struct vfpga_dev **)netdev_priv(vfpga->ndev);
    //dbg_info("vfpga_net_register check_priv: NAPI struct address: %p\n", &check_priv->napi);
    //dbg_info("napi.dev=%p, ndev=%p\n", check_priv->napi.dev, check_priv->ndev);
    //dbg_info("napi.poll=%p\n", check_priv->napi.poll);

    return 0;
}

// Unregister the FPGA-NIC
void vfpga_net_unregister(struct vfpga_dev *vfpga)
{
    //dbg_info("Trying to unregister the network device\n");
    if (vfpga->ndev) {
        //dbg_info("Found a valid net_device, trying to unregister\n");
        unregister_netdev(vfpga->ndev);
        //dbg_info("Finished unregistering the network device\n");
        // free_netdev(fpga->ndev);
        //dbg_info("Finished freeing the net_device\n");
        pr_info("fpga_net: device unregistered\n");
    } else {
        return; 
    }
}

meta_tag_decoded_t decode_meta_tag(uint32_t raw) {
    meta_tag_decoded_t decoded; 
    decoded.possession_flag = (raw >> 31) & 0x1;
    decoded.packet_len = (raw >> 3) & 0x0FFFFFFF;
    decoded.rsvd = raw & 0x7;
    return decoded;
}
