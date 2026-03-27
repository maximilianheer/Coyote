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
    // Step 1: Check if the specified operation is supported in the current setting and if the buffer is not too long
    if (!isLocalRead(oper) && !isLocalWrite(oper)) {
        return -EINVAL;
    }

    if (sg.len > MAX_TRANSFER_SIZE) {
        return -EINVAL;
    }

    // Step 2: Dissect the meta-information to create the required arguments for calling the post_command function
    uint64_t ctrl_cmd_src = 0;
    uint64_t ctrl_cmd_dst = 0;
    uint64_t addr_cmd_src = 0;
    uint64_t addr_cmd_dst = 0;

    if(oper == LOCAL_READ) {
        // Process a LOCAL READ 
        ctrl_cmd_src = ((vfpga_net_ctid & CTRL_PID_MASK) << CTRL_PID_OFFS) |
                ((sg.dest & CTRL_DEST_MASK) << CTRL_DEST_OFFS) |
                (last ? CTRL_LAST : 0x0) |
                ((sg.stream & CTRL_STRM_MASK) << CTRL_STRM_OFFS) |
                (CTRL_START) |
                (0x0) |
                ((uint64_t)(sg.len) << CTRL_LEN_OFFS);

        addr_cmd_src = (uint64_t)(sg.addr);

        vfpga_net_post_command(vfpga, addr_cmd_dst, ctrl_cmd_dst, addr_cmd_src, ctrl_cmd_src);
    } else if(oper == LOCAL_WRITE) {
        // Process a LOCAL WRITE
        ctrl_cmd_dst = ((vfpga_net_ctid & CTRL_PID_MASK) << CTRL_PID_OFFS) |
            ((sg.dest & CTRL_DEST_MASK) << CTRL_DEST_OFFS) |
            (last ? CTRL_LAST : 0x0) |
            ((sg.stream & CTRL_STRM_MASK) << CTRL_STRM_OFFS) |
            (CTRL_START) |
            (0x0) |
            ((uint64_t)(sg.len) << CTRL_LEN_OFFS);

        addr_cmd_dst = (uint64_t)(sg.addr);

        vfpga_net_post_command(vfpga, addr_cmd_dst, ctrl_cmd_dst, addr_cmd_src, ctrl_cmd_src);
    } else {
        // Unsupported operation type
        return -EINVAL;
    }

    // Return 0 success in the end 
    return 0;
}

// Function for polling the writeback region to check for operation completion 
uint32_t vfpga_net_check_completed(struct vfpga_dev *vfpga, CoyoteOper oper) {
    // Based on operation type, check the corresponding writeback entry
    if(isLocalWrite(oper)) {
        return vfpga->vfpga_net_wb[vfpga_net_ctid + WR_WBACK * N_CTID_MAX];
    } else if(isLocalRead(oper)) {
        return vfpga->vfpga_net_wb[vfpga_net_ctid + RD_WBACK * N_CTID_MAX];
    } else {
        return 0;
    }
}

// Function for clearing the writeback entry after operation completion
void vfpga_net_clear_completed(struct vfpga_dev *vfpga) {
    vfpga->vfpga_net_wb[vfpga_net_ctid + RD_WBACK * N_CTID_MAX] = 0;
    vfpga->vfpga_net_wb[vfpga_net_ctid + WR_WBACK * N_CTID_MAX] = 0;
}

// Function for opening the new FPGA-NIC
static int vfpga_net_open(struct net_device *dev)
{
    struct vfpga_dev *vfpga = *(struct vfpga_dev **)netdev_priv(dev);


    // Check if all required pointers are valid before proceeding with the initialization; if not, return an error code (ideally this should never happen, but we want to be safe here)
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


    // Initialize the TX lock and start the queue 
    spin_lock_init(&vfpga->tx_lock);
    
    // Control-mmap 
    vfpga->vfpga_net_ctrl = ioremap((vfpga->vfpga_cnfg_phys_addr + VFPGA_CTRL_USER_OFFS), VFPGA_CTRL_USER_SIZE); 
    if(vfpga->vfpga_net_ctrl == NULL) {
        return -ENOMEM; 
    }

    // Config-mmap -> Used for giving commands to the FPGA 
    vfpga->vfpga_net_cnfg = ioremap(vfpga->vfpga_cnfg_avx_phys_addr, VFPGA_CTRL_CNFG_AVX_SIZE); 
    if(vfpga->vfpga_net_cnfg == NULL) {
        return -ENOMEM; 
    }

    // Writeback buffer is host RAM (dma_alloc_coherent); use wb_addr_virt directly
    // instead of ioremap, which would create an uncached MMIO mapping and turn
    // every completion read into a slow PCIe round-trip.
    vfpga->vfpga_net_wb = (volatile uint32_t *)vfpga->wb_addr_virt;

    // Also, reset the current counter of outstanding commands to the FPGA to later be able to work efficiently with this command pipeline 
    vfpga->cmd_cnt = 0;


    // Pass on the hpid 17 for the NIC as arg to the ioctl call 
    uint64_t tmp_reg_ctid[32];
    tmp_reg_ctid[0] = current->pid;

    if(vfpga_dev_ioctl_functionality(vfpga, IOCTL_REGISTER_CTID, (uint64_t)&tmp_reg_ctid, true) < 0 ) {
        //dbg_info("Couldn't register a ctid for the FPGA-NIC. \n"); 
        return -ENOMEM; 
    } else {
        // On success, read back the allocated ctid from the arg array
        vfpga_net_ctid = tmp_reg_ctid[1];  
    }

    // Allocate the RX-buffer for the net-device 
    vfpga->vfpga_net_rx_buf = dma_alloc_coherent(&vfpga->bd_data->pci_dev->dev, RX_BUFF_SIZE, &vfpga->vfpga_net_rx_buf_phys_addr, GFP_KERNEL);
    if(!vfpga->vfpga_net_rx_buf) {
        dbg_info("Couldn't allocate the RX-buffer for the net-device. \n"); 
        return -ENOMEM; 
    } 

    // Allocate the TX-buffer for the net-device 
    vfpga->vfpga_net_tx_buf = dma_alloc_coherent(&vfpga->bd_data->pci_dev->dev, TX_BUFF_SIZE, &vfpga->vfpga_net_tx_buf_phys_addr, GFP_KERNEL);
    if(!vfpga->vfpga_net_tx_buf) {
        dbg_info("Couldn't allocate the TX-buffer for the net-device. \n");
        return -ENOMEM;
    }

    // Initialise TX ring indices
    vfpga->tx_head      = 0;
    vfpga->tx_completed = 0;

    // Add both the TX- and RX-buffers to the kernel buffer map for the given ctid
    tlb_get_kernel_buffers(vfpga, (uint64_t)(((uint64_t)vfpga->vfpga_net_rx_buf & 0xFFFFFFFFFFFFULL) >> 12), vfpga->vfpga_net_rx_buf_phys_addr, vfpga_net_ctid, RX_BUFF_SIZE);
    tlb_get_kernel_buffers(vfpga, (uint64_t)(((uint64_t)vfpga->vfpga_net_tx_buf & 0xFFFFFFFFFFFFULL) >> 12), vfpga->vfpga_net_tx_buf_phys_addr, vfpga_net_ctid, TX_BUFF_SIZE);

    // Initialize our debugging flags in the vFPGA to 0 
    vfpga->rx_buf_cycle_cnt = 0;
    vfpga->rx_buf_first_pkt_flag = 0;
    vfpga->rx_buf_stuck_flag = 0;
    vfpga->iperf_pkt_cnt = 0;

    // -----------------------
    // AXI-CTRL to the vFPGA 
    // -----------------------

    // Offset 0: HOST_NETWORKING_PID
    writeq(vfpga_net_ctid, vfpga->vfpga_net_ctrl + 0);

    // Offset 1: RX_BUFF_VADDR
    writeq((uint64_t)vfpga->vfpga_net_rx_buf, vfpga->vfpga_net_ctrl + 1);

    // Offset 2: HOST_NETWORKING_BUFF_STRIDE 
    writeq(BUFFER_STRIDE, vfpga->vfpga_net_ctrl + 2);

    // Offset 3: HOST_NETWORKING_RING_SIZE
    // Use 511 instead of 512 to leave one sentinel slot, preventing the
    // aliasing deadlock where fp_wp == ring_head (mod ring_size) is
    // ambiguous between "ring empty" and "ring full" at full saturation.
    writeq(BUFFER_RING_SIZE, vfpga->vfpga_net_ctrl + 3);

    // Offset 4: HOST_NETWORKING_RING_HEAD 
    writeq(0, vfpga->vfpga_net_ctrl + 4);

    // Offset 6: HOST_NETWORKING_IRQ_COALESCE
    writeq(32, vfpga->vfpga_net_ctrl + 6);

    // Offset 7: HOST_NETWORKING_IRQ_TIMEOUT
    writeq(500, vfpga->vfpga_net_ctrl + 7);

    pr_info("vfpga_net: device %s opened\n", dev->name);

    // Safety checks 
    BUG_ON(!vfpga->ndev);
    BUG_ON(!&vfpga->napi);

    // Preflight Check #1: Check that ndev is valid and not null 
    if(!vfpga->ndev) {
        dbg_info("vfpga_net_open: vfpga->ndev is NULL!\n");
        return -ENOMEM; // Or handle the error gracefully
    }

    // Enable the NAPI and start the queue for packet transmission 
    napi_enable(&vfpga->napi);
    netif_start_queue(dev);

    // Tell the kernel the physical link is up
    netif_carrier_on(dev);

    // Return success 
    return 0;
}

// Function for stopping the FPGA-NIC 
static int vfpga_net_stop(struct net_device *dev)
{
    struct vfpga_dev *vfpga = *(struct vfpga_dev **)netdev_priv(dev);

    // Stop the queue 
    netif_stop_queue(dev);

    // Set the RX-Buf addr in the hardware to 0 to stop HW-functionality 
    writeq(0, vfpga->vfpga_net_ctrl + 0);


    // Buffer deallocation for the vFPGA, using ioremap for kernelspace mapping 
    iounmap(vfpga->vfpga_net_ctrl); 
    pr_info("vfpga_net: device %s closed\n", dev->name);
    return 0;
}

// Function that is called when the FPGA issues an interrupt for packet reception at threshold 
void vfpga_net_irq_dispatch(struct vfpga_dev *vfpga)
{
    // Schedule a napi-call 
    napi_schedule(&vfpga->napi);
}

// Function that polls the RX-ring buffer for new packets and handles their processing within the Linux network stack 
static int vfpga_net_poll(struct napi_struct *napi, int budget)
{
    // Get the vfpga device structure from the napi struct
    struct vfpga_dev *vfpga = container_of(napi, struct vfpga_dev, napi);

    // Count the number of packets processed (must not exceed the budget given during registration)
    int packets_processed = 0;

    // Keep on processing packets until we reach the budget limit or there are no more packets left to process 
    while(packets_processed < budget && vfpga_rx_has_packet(vfpga)) {
        // Fetch the packet from the RX-ring buffer
        struct sk_buff *skb = vfpga_rx_fetch_packet(vfpga);

        // Stop processing if there's no skb 
        if(!skb) {
            break;
        }

        // Pass the packet to the network stack
        napi_gro_receive(napi, skb);

        // Update the number of processed packets 
        packets_processed++;
    }

    // Write the updated consumer pointer back to the FPGA hardware so that the
    // edge-triggered IRQ threshold can re-arm for the next incoming packet.
    // Without this, (write_ptr - ring_head_reg) never drops back below the
    // coalesce threshold and no further RX interrupts are generated.
    // IMPORTANT: must happen BEFORE napi_complete_done() re-enables IRQs.
    // Writing after completing opens a race: a concurrent poll on another CPU
    // can advance rx_buf_head and write it to HW first; our stale write would
    // then regress the hardware ring pointer, starving the FPGA's RX write path.
    /* if (packets_processed > 0) {
        dbg_info("vfpga_net_poll: Processed %d packets. \n", packets_processed);
        writeq(vfpga->rx_buf_head, vfpga->vfpga_net_ctrl + 4);
    } */ 

    // If we returned less than the full budget, we are done for this round.
    // napi_complete_done() MUST be called in this case to clear NAPI_STATE_SCHED;
    // without it, subsequent napi_schedule() calls in the IRQ handler are no-ops
    // and polling never restarts (even though the hardware keeps firing interrupts).
    if(packets_processed < budget) {
        napi_complete_done(napi, packets_processed);
    }

    // Reclaim any TX completions that arrived while we were polling RX, and
    // restart the TX queue if it was stopped due to a full ring.
    spin_lock(&vfpga->tx_lock);
    uint32_t tx_done = vfpga_net_check_completed(vfpga, LOCAL_READ);
    if (tx_done > vfpga->tx_completed) {
        // Update the number of processed TX-packets 
        vfpga->tx_completed = tx_done;
        if (netif_queue_stopped(vfpga->ndev) &&
            (vfpga->tx_head - vfpga->tx_completed) < TX_NUM_SLOTS)
            netif_wake_queue(vfpga->ndev);
    }
    spin_unlock(&vfpga->tx_lock);

    // Return the number of processed packets to the kernel 
    return packets_processed;
}

// Function to check if there is a packet available in the RX-ring buffer at the next position 
static bool vfpga_rx_has_packet(struct vfpga_dev *vfpga)
{
    // dbg_info("vfpga_rx_has_packet: Checking for new packet at RX buffer head index %u. \n", vfpga->rx_buf_head);
    // Calculate pointer to the meta word of the current RX slot
    uint8_t *base_ptr = (uint8_t *)vfpga->vfpga_net_rx_buf;
    uint8_t *pkt_ptr = base_ptr + vfpga->rx_buf_head * BUFFER_STRIDE;
    uint32_t *meta_word_ptr = (uint32_t *)(pkt_ptr);
    // dbg_info("vfpga_rx_has_packet: Base pointer address: %p, packet pointer address: %p. \n", base_ptr, pkt_ptr);
    // dbg_info("vfpga_rx_has_packet: Meta word pointer address: %p. \n", meta_word_ptr);

    // Read raw meta word from DMA buffer
    dma_sync_single_for_cpu(&vfpga->bd_data->pci_dev->dev,
                        vfpga->vfpga_net_rx_buf_phys_addr +
                        (vfpga->rx_buf_head * BUFFER_STRIDE),
                        sizeof(uint32_t), DMA_FROM_DEVICE);
    uint32_t raw_meta = *meta_word_ptr;
    // dbg_info("vfpga_rx_has_packet: Raw meta word value: 0x%08x. \n", raw_meta);

    // Decode the meta word
    meta_tag_decoded_t meta;
    meta.possession_flag = (raw_meta >> 31) & 0x1;
    meta.packet_len      = (raw_meta >> 3)  & 0x0FFFFFFF;
    meta.rsvd            = raw_meta & 0x7;

    // dbg_info("vfpga_rx_has_packet: Meta tag - possession_flag: %u, packet_len: %u, rsvd: %u. \n", meta.possession_flag, meta.packet_len, meta.rsvd);

    // Return true if FPGA owns the packet (flag=1)
    return (meta.possession_flag == 1);
}

// Function to fetch the packet from the RX-ring buffer at the current position and hand it over to the network stack
static struct sk_buff *vfpga_rx_fetch_packet(struct vfpga_dev *vfpga)
{
    // Calculate pointer to the packet of the current RX slot
    uint8_t *base_ptr = (uint8_t *)vfpga->vfpga_net_rx_buf;
    uint8_t *pkt_ptr = base_ptr + vfpga->rx_buf_head * BUFFER_STRIDE;
    uint32_t *meta_word_ptr = (uint32_t *)(pkt_ptr);

    // Read raw meta word from DMA buffer
    uint32_t raw_meta = *meta_word_ptr;

    // Decode the meta word
    meta_tag_decoded_t meta;
    meta.possession_flag = (raw_meta >> 31) & 0x1;
    meta.packet_len      = (raw_meta >> 3)  & 0x0FFFFFFF;
    meta.rsvd            = raw_meta & 0x7;

    // One more check to ensure the possession flag is set
    if(meta.possession_flag == 0) {
        // dbg_info("vfpga_rx_fetch_packet: Packet at RX buffer head index %u does not have possession flag set. \n", vfpga->rx_buf_head);
        return NULL;
    }

    // For fetching the actual packet: Read out the packet length from the meta-tag and calculate the packet start address
    size_t pkt_len = meta.packet_len;
    void *actual_pkt_addr = (void *)(meta_word_ptr + 1);

    // If packet length is 1514, this is a iperf packet and we count it for debugging purposes by setting a flag in the vFPGA; this allows us to correlate the number of iperf packets we receive with the number of times we circle around in the RX buffer, which gives us insights into how many iperf packets we can store in the RX buffer before we start dropping them
    /* if(pkt_len == 1514) {
        vfpga->iperf_pkt_cnt++;
        dbg_info("vfpga_rx_fetch_packet: Received iperf packet at RX buffer head index %u, total iperf packets received so far: %u. \n", vfpga->rx_buf_head, vfpga->iperf_pkt_cnt);
    }

    // If this is the first iperf packet, we store the position of the buf head in the vFPGA for debugging purposes; this allows us to correlate the position of the first iperf packet in the RX buffer with the number of packets we can receive before we start dropping them, which gives us insights into how many non-iperf packets we receive before we can store an iperf packet in the RX buffer
    if(pkt_len == 1514 && vfpga->rx_buf_first_pkt_flag == 0) {
        vfpga->rx_buf_first_pkt_flag = vfpga->rx_buf_head;
    } */ 

    // Allocate a new skb for the packet
    struct sk_buff *skb = netdev_alloc_skb(vfpga->ndev, pkt_len);
    if(!skb) {
        dbg_info("vfpga_rx_fetch_packet: Failed to allocate skb for incoming packet. \n");
        return NULL;
    }

    // Copy the packet data into the skb
    dma_sync_single_for_cpu(&vfpga->bd_data->pci_dev->dev,
                        vfpga->vfpga_net_rx_buf_phys_addr +
                        (vfpga->rx_buf_head * BUFFER_STRIDE) + sizeof(uint32_t),
                        pkt_len, DMA_FROM_DEVICE);
    memcpy(skb_put(skb, pkt_len), actual_pkt_addr, pkt_len);

    // Update the stats for incoming packets and bytes
    vfpga->ndev->stats.rx_packets++;
    vfpga->ndev->stats.rx_bytes += pkt_len;

    // Set the protocol and checksum fields in the skb for proper handling in the network stack
    skb->protocol = eth_type_trans(skb, vfpga->ndev);
    skb->ip_summed = CHECKSUM_UNNECESSARY; // Hand over checksum checking to the network stack

    // Clear the possession flag in the meta-tag to indicate the packet has been processed
    meta.possession_flag = 0;
    raw_meta = (meta.possession_flag << 31) |
                    ((meta.packet_len & 0x0FFFFFFF) << 3) |
                    (meta.rsvd & 0x7);
    *(uint32_t *)meta_word_ptr = raw_meta;

    wmb();

    // Update the RX buffer head to the next position (wrap around if necessary)
    vfpga->rx_buf_head = (vfpga->rx_buf_head + 1) % BUFFER_RING_SIZE;

    // If the buf head is 0, we wrapped around and store that in the vFPGA for debugging purposes
    if(vfpga->rx_buf_head == 0) {
        vfpga->rx_buf_cycle_cnt++;
        dbg_info("vfpga_rx_fetch_packet: Wrapped around RX buffer, cycle count: %u. \n", vfpga->rx_buf_cycle_cnt);
    }

    return skb;
}

// Function for transmitting packets
static netdev_tx_t vfpga_net_xmit(struct sk_buff *skb, struct net_device *dev)
{
    struct vfpga_dev *vfpga = *(struct vfpga_dev **)netdev_priv(dev);
    unsigned long flags;

    size_t pkt_len = skb->len;

    // Check if the packet length is allowed 
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
        vfpga->tx_completed = done;
    }

    // Ring full? Stop the queue; NAPI poll will restart it once slots free up.
    if ((vfpga->tx_head - vfpga->tx_completed) >= TX_NUM_SLOTS) {
        netif_stop_queue(dev);
        spin_unlock_irqrestore(&vfpga->tx_lock, flags);
        return NETDEV_TX_BUSY;
    }

    // Copy the packet into the next free slot.
    uint32_t slot = vfpga->tx_head % TX_NUM_SLOTS;
    uint8_t *slot_ptr = (uint8_t *)vfpga->vfpga_net_tx_buf + (size_t)slot * BUFFER_STRIDE;
    memcpy(slot_ptr, skb->data, pkt_len);
    wmb();

    // Trigger the LOCAL_READ for this slot.
    struct localSg sg = LOCAL_SG_INIT;
    sg.addr   = slot_ptr;
    sg.stream = 1;
    sg.dest   = 0;
    sg.len    = pkt_len;
    vfpga_net_invoke_local_op(vfpga, LOCAL_READ, sg, true);

    vfpga->tx_head++;

    spin_unlock_irqrestore(&vfpga->tx_lock, flags);

    dev->stats.tx_packets++;
    dev->stats.tx_bytes += pkt_len;
    dev_kfree_skb(skb);
    return NETDEV_TX_OK;
}

// TX watchdog: called by the kernel if the TX queue has been stopped for too long.
// Schedules NAPI to reclaim completions and restarts the queue, breaking the
// TX/RX deadlock without bringing the interface down (which would lose the IP).
static void vfpga_net_tx_timeout(struct net_device *dev, unsigned int txqueue)
{
    struct vfpga_dev *vfpga = *(struct vfpga_dev **)netdev_priv(dev);
    napi_schedule(&vfpga->napi);
    netif_wake_queue(dev);
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
}

// Function to get driver info for ethtool
static void vfpga_net_get_drvinfo(struct net_device *dev,
                          struct ethtool_drvinfo *info)
{
    strscpy(info->driver, "scenic_driver", sizeof(info->driver));
    strscpy(info->version, "0.1", sizeof(info->version));
    strscpy(info->bus_info, "PCIe", sizeof(info->bus_info));
}

// Function to get link status for ethtool 
static u32 vfpga_net_get_link(struct net_device *dev)
{
    return netif_carrier_ok(dev); 
}

// Function to get link ksettings for ethtool
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
    return 0;
}


// Struct that points to all the functions of the FPGA-NIC in the driver 
static const struct net_device_ops vfpga_netdev_ops = {
    .ndo_open        = vfpga_net_open,
    .ndo_stop        = vfpga_net_stop,
    .ndo_start_xmit  = vfpga_net_xmit,
    .ndo_get_stats64 = vfpga_net_get_stats64,
    .ndo_tx_timeout  = vfpga_net_tx_timeout,
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
    int ret_val;

    // Allocate the net device structure
    vfpga->ndev = alloc_netdev(sizeof(struct vfpga_dev *), "scenic_%d",
                          NET_NAME_UNKNOWN, ether_setup);
    if (!vfpga->ndev) {
        pr_err("fpga_net: could not allocate net device\n");
        return -ENOMEM;
    }

    vfpga->ndev->max_mtu = 4096;

    // Set the device operations
    vfpga->ndev->netdev_ops = &vfpga_netdev_ops;

    // Set the ethtool operations 
    vfpga->ndev->ethtool_ops = &vfpga_ethtool_ops;

    // Set the MAC address (for simplicity, using a fixed MAC address here)
    uint8_t mac_bytes[ETH_ALEN];
    for (int i = 0; i < ETH_ALEN; i++){
        mac_bytes[i] = (net_mac_addr >> (8 * (ETH_ALEN - 1 - i))) & 0xFF;
    }

    vfpga->ndev->addr_len = ETH_ALEN; 
    if(is_valid_ether_addr(mac_bytes)) {
        eth_hw_addr_set(vfpga->ndev, mac_bytes);
    } else {
        eth_hw_addr_random(vfpga->ndev); // Random MAC address for demonstration
    }

    // Bind the NAPI-poll function during registration 
    vfpga->napi.dev = vfpga->ndev;
    vfpga->napi.poll = vfpga_net_poll;
    netif_napi_add(vfpga->ndev, &vfpga->napi, vfpga_net_poll);
    pr_info("After netif_napi_add: napi.dev=%p napi.poll=%p \n",
        vfpga->napi.dev, vfpga->napi.poll);

    // Register the network device. Keep carrier off until register_netdev
    // succeeds, then immediately assert carrier-on so that NetworkManager /
    // systemd-networkd see the link as permanently up and do not tear down
    // any IP configuration that was assigned before ndo_open is called.
    netif_carrier_off(vfpga->ndev);
    ret_val = register_netdev(vfpga->ndev);
    if (ret_val) {
        pr_err("fpga_net: could not register net device\n");
        free_netdev(vfpga->ndev);
        return ret_val;
    }
    netif_carrier_on(vfpga->ndev);

    pr_info("fpga_net: device %s registered with MAC %pM\n", vfpga->ndev->name, vfpga->ndev->dev_addr);

    // struct vfpga_dev *priv = netdev_priv(vfpga->ndev);
    struct vfpga_dev **priv_ptr = netdev_priv(vfpga->ndev);
    *priv_ptr = vfpga;

    // Printing the napi stored in priv of ndev
    struct vfpga_dev *check_priv = *(struct vfpga_dev **)netdev_priv(vfpga->ndev);

    return 0;
}

// Unregister the FPGA-NIC
void vfpga_net_unregister(struct vfpga_dev *vfpga)
{
    if (vfpga->ndev) {
        unregister_netdev(vfpga->ndev);
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
