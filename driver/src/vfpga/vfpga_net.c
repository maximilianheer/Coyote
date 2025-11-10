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

// ======-------------------------------------------------------------------------------
//
// FPGA network functions - Exposes Coyote as a proper NIC to the system 
//
// ======-------------------------------------------------------------------------------

// Global variable for the ctid used by the FPGA-NIC 
int32_t vfpga_net_ctid = -1;

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

// Function for opening the new FPGA-NIC
static int vfpga_net_open(struct net_device *dev)
{
    struct vfpga_dev *vfpga = netdev_priv(dev);

    // Initialize the TX lock and start the queue 
    spin_lock_init(&vfpga->tx_lock);

    dbg_info("vfpga_net_open at the beginning: NAPI struct address: %p\n", &vfpga->napi);
    dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    dbg_info("napi.poll=%p\n", vfpga->napi.poll);

    // Buffer allocation for the vFPGA, using ioremap for kernelspace mapping 
    
    // Control-mmap 
    dbg_info("Trying to allocate net ctrl memory at %llx of size %d.\n", vfpga->vfpga_cnfg_phys_addr+VFPGA_CTRL_USER_OFFS, VFPGA_CTRL_USER_SIZE); 
    vfpga->vfpga_net_ctrl = ioremap((vfpga->vfpga_cnfg_phys_addr + VFPGA_CTRL_USER_OFFS), VFPGA_CTRL_USER_SIZE); 
    if(vfpga->vfpga_net_ctrl == NULL) {
        dbg_info("Couldn't allocate control memory.");
        return -ENOMEM; 
    } else {
        dbg_info("Successfully allocated the net ctrl memory at %llx.\n", *vfpga->vfpga_net_ctrl);
    }

    // Config-mmap 
    /* dbg_info("Trying to allocate net cnfg memory at %llx of size %lx.\n", vfpga->vfpga_cnfg_avx_phys_addr, VFPGA_CTRL_CNFG_AVX_SIZE); 
    vfpga->vfpga_net_cnfg = ioremap(vfpga->vfpga_cnfg_avx_phys_addr, VFPGA_CTRL_CNFG_AVX_SIZE); 
    if(vfpga->vfpga_net_cnfg == NULL) {
        dbg_info("Couldn't allocate config memory."); 
        return -ENOMEM; 
    } else {
        dbg_info("Successfully allocated the net cnfg memory. \n"); 
    }

    // Writeback-mmap
    dbg_info("Trying to allocate writeback memory at %llx of size %lx. \n", vfpga->wb_phys_addr, WB_SIZE);
    vfpga->vfpga_net_wb = ioremap(vfpga->wb_phys_addr, WB_SIZE);
    if(vfpga->vfpga_net_wb == NULL) {
        dbg_info("Couldn't allocate writeback memory."); 
        return -ENOMEM; 
    } else {
        dbg_info("Successfully allocated the net writeback memory. \n"); 
    } */ 

    // Allocate the RX- and TX-buffer for packet transmission 
    dbg_info("Trying to allocate the RX-buffer for arbitrary packet reception. \n"); 

    if (!vfpga) {
        dbg_info("VFPGA CRASH: vfpga is NULL!\n");
        return -ENOMEM; // Or handle the error gracefully
    }

    // 1. Check bd_data
    if (!vfpga->bd_data) {
        dbg_info("VFPGA CRASH: bd_data is NULL.\n");
        return -ENOMEM;
    }

    // 2. Check pci_dev
    if (!vfpga->bd_data->pci_dev) {
        dbg_info("VFPGA CRASH: pci_dev is NULL.\n");
        return -ENOMEM;
    }

    // 3. Check the internal 'dev' pointer (the struct device)
    /* if (vfpga->bd_data->pci_dev->dev == NULL) {
        dbg_info("VFPGA CRASH: struct device reference is NULL.\n");
        return -ENOMEM;
    } */ 

    dbg_info("Printing the RX Buf physical address %llx \n", vfpga->vfpga_net_rx_buf_phys_addr);

    // Call ioctl for registering the ctid. We assume a fixed hpid of 17 for the NIC. 
    dbg_info("Trying to register a ctid for the FPGA-NIC. \n"); 

    // Pass on the hpid 17 for the NIC as arg to the ioctl call 
    uint64_t tmp_reg_ctid[32];
    tmp_reg_ctid[0] = current->pid;

    // Print the current pid 
    dbg_info("Current process pid is %d \n", current->pid);

    if(vfpga_dev_ioctl_functionality(vfpga, IOCTL_REGISTER_CTID, (uint64_t)&tmp_reg_ctid, true) < 0 ) {
        dbg_info("Couldn't register a ctid for the FPGA-NIC. \n"); 
        return -ENOMEM; 
    } else {
        // On success, read back the allocated ctid from the arg array
        vfpga_net_ctid = tmp_reg_ctid[1];  
        dbg_info("Successfully registered ctid %d for the FPGA-NIC. \n", vfpga_net_ctid); 
    }

    dbg_info("Trying to allocate the RX-buffer for arbitrary packet reception. \n"); 
    vfpga->vfpga_net_rx_buf = dma_alloc_coherent(&vfpga->bd_data->pci_dev->dev, RX_BUFF_SIZE, &vfpga->vfpga_net_rx_buf_phys_addr, GFP_KERNEL);
    if(!vfpga->vfpga_net_rx_buf) {
        dbg_info("Couldn't allocate the RX-buffer for the net-device. \n"); 
        return -ENOMEM; 
    } else {
        dbg_info("Successfully allocated the RX-buffer for the net-device at %llx. \n", *vfpga->vfpga_net_rx_buf); 
    }

    dbg_info("Trying to allocate the TX-buffer for arbitrary packet reception. \n"); 
    vfpga->vfpga_net_tx_buf = dma_alloc_coherent(&vfpga->bd_data->pci_dev->dev, TX_BUFF_SIZE, &vfpga->vfpga_net_tx_buf_phys_addr, GFP_KERNEL);
    if(!vfpga->vfpga_net_tx_buf) {
        dbg_info("Couldn't allocate the TX-buffer for the net-device. \n"); 
        return -ENOMEM; 
    } else {
        dbg_info("Successfully allocated the TX-buffer for the net-device at %llx. \n", *vfpga->vfpga_net_tx_buf); 
    }

    // Add both the TX- and RX-buffers to the kernel buffer map for the given ctid
    dbg_info("Adding the RX-buffer to the kernel buffer map for ctid %d. \n", vfpga_net_ctid);
    tlb_get_kernel_buffers(vfpga, (uint64_t)(((uint64_t)vfpga->vfpga_net_rx_buf & 0xFFFFFFFFFFFFULL) >> 12), vfpga->vfpga_net_rx_buf_phys_addr, vfpga_net_ctid, RX_BUFF_SIZE);
    dbg_info("Adding the TX-buffer to the kernel buffer map for ctid %d. \n", vfpga_net_ctid);
    tlb_get_kernel_buffers(vfpga, (uint64_t)(((uint64_t)vfpga->vfpga_net_tx_buf & 0xFFFFFFFFFFFFULL) >> 12), vfpga->vfpga_net_tx_buf_phys_addr, vfpga_net_ctid, TX_BUFF_SIZE);
    dbg_info("Successfully added both RX- and TX-buffers to the kernel buffer map for ctid %d. \n", vfpga_net_ctid);

    // -----------------------
    // AXI-CTRL to the vFPGA 
    // -----------------------

    // ssleep(1);

    // Offset 0: HOST_NETWORKING_PID
    dbg_info("Write host-pid 0 to ctrl-reg. \n");
    writeq(vfpga_net_ctid, vfpga->vfpga_net_ctrl + 0);
    // iowrite64(0, vfpga->vfpga_net_rx_buf + 1); 
    // vfpga->vfpga_net_rx_buf[1] = 0; 

    // Offset 1: RX_BUFF_VADDR
    dbg_info("Write RX-buffer address %llx to ctrl-reg. \n", *vfpga->vfpga_net_rx_buf);
    writeq((uint64_t)vfpga->vfpga_net_rx_buf, vfpga->vfpga_net_ctrl + 1);
    // iowrite64(vfpga->vfpga_net_rx_buf, vfpga->vfpga_net_rx_buf); 
    // vfpga->vfpga_net_rx_buf[0] = vfpga->vfpga_net_rx_buf; 

    // Offset 2: HOST_NETWORKING_BUFF_STRIDE 
    dbg_info("Write buff_stride 6144 to ctrl-reg. \n");
    writeq(6144, vfpga->vfpga_net_ctrl + 2);
    // iowrite64(6144, vfpga->vfpga_net_rx_buf + 2); 
    // vfpga->vfpga_net_rx_buf[2] = 6144; 

    // Offset 3: HOST_NETWORKING_RING_SIZE
    dbg_info("Write ring_size 512 to ctrl-reg. \n");
    writeq(512, vfpga->vfpga_net_ctrl + 3);
    // iowrite64(512, vfpga->vfpga_net_rx_buf + 3); 
    // vfpga->vfpga_net_rx_buf[3] = 512; 

    // Offset 4: HOST_NETWORKING_RING_HEAD 
    dbg_info("Write ring head 0 to ctrl-reg. \n");
    writeq(0, vfpga->vfpga_net_ctrl + 4);
    // vfpga->vfpga_net_rx_buf[4] = 0; 
    // iowrite64(0, vfpga->vfpga_net_rx_buf + 4); 


    // Offset 5: HOST_NETWORKING_IRQ_COALESCE
    dbg_info("Write irq coalesce 16 to ctrl-reg. \n");
    writeq(16, vfpga->vfpga_net_ctrl + 6);
    // vfpga->vfpga_net_rx_buf[5] = 16; 
    // iowrite64(16, vfpga->vfpga_net_rx_buf + 5); 


    pr_info("vfpga_net: device %s opened\n", dev->name);

    // Enable the NAPI polling for the FPGA-NIC
    dbg_info("Enabling NAPI polling for the FPGA-NIC. \n");
    BUG_ON(!vfpga->ndev);
    BUG_ON(!&vfpga->napi);

    // Preflight Check #1: Check that ndev is valid and not null 
    if(!vfpga->ndev) {
        dbg_info("vfpga_net_open: vfpga->ndev is NULL!\n");
        return -ENOMEM; // Or handle the error gracefully
    }

    // Preflight Check #2: Print the contents of the napi struct to ensure it exists
    dbg_info("vfpga_net_open at the end: NAPI struct address: %p\n", &vfpga->napi);
    dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    // struct napi_struct *napi = &vfpga->napi;
    napi_enable(&vfpga->napi);
    netif_start_queue(dev);
    dbg_info("Successfully started the netif queue for the FPGA-NIC. \n");

    return 0;
}

// Function for stopping the FPGA-NIC 
static int vfpga_net_stop(struct net_device *dev)
{
    struct vfpga_dev *vfpga = netdev_priv(dev);

    // Stop the queue 
    netif_stop_queue(dev);

    // Set the RX-Buf addr in the hardware to 0 to stop HW-functionality 
    dbg_info("Write RX-buffer address 0 to ctrl-reg. \n");
    writeq(0, vfpga->vfpga_net_ctrl + 0);


    // Buffer deallocation for the vFPGA, using ioremap for kernelspace mapping 
    dbg_info("Trying to deallocate the buffers held for ctrl, cnfg and wb of the vFPGA. \n"); 
    iounmap(vfpga->vfpga_net_ctrl); 
    // iounmap(vfpga->vfpga_net_cnfg); 
    // iounmap(vfpga->vfpga_net_wb); 
    dbg_info("Successfully deallocated the buffers held for ctrl, cnfg and wb of the vFPGA. \n"); 

    // Deallocating the RX- and TX-buffer for the net-device 
    dbg_info("Trying to deallocate the RX- and TX buffers held for the net vFPGA. \n"); 
    // dma_free_coherent(&vfpga->bd_data->pci_dev->dev, RX_BUFF_SIZE, vfpga->vfpga_net_rx_buf, &vfpga->vfpga_net_rx_buf_phys_addr); 
    // dma_free_coherent(&vfpga->bd_data->pci_dev->dev, TX_BUFF_SIZE, vfpga->vfpga_net_tx_buf, &vfpga->vfpga_net_tx_buf_phys_addr); 
    dbg_info("Successfully deallocated the RX- and TX-buffers held for the net vFPGA. \n"); 


    // Stopping of the hardware etc. 

    pr_info("vfpga_net: device %s closed\n", dev->name);
    return 0;
}

// Function that is called when the FPGA issues an interrupt for packet reception at threshold 
void vfpga_net_irq_dispatch(struct vfpga_dev *vfpga)
{
    // NAPI poll call to handle the packet reception 
    dbg_info("Dispatching NAPI poll for FPGA-NIC \n"); 
    dbg_info("vfpga_net_irq_dispatch: NAPI struct address: %p\n", &vfpga->napi);
    dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    napi_enable(&vfpga->napi);
    napi_schedule(&vfpga->napi);
}

// Function that polls the RX-ring buffer for new packets and handles their processing within the Linux network stack 
static int vfpga_net_poll(struct napi_struct *napi, int budget)
{
    dbg_info("vfpga_net_poll: Polling the RX-ring buffer for new packets from the FPGA-NIC. \n");
    return 0; 

    // Get the vfpga device structure from the napi struct
    struct vfpga_dev *vfpga = container_of(napi, struct vfpga_dev, napi);
    dbg_info("vfpga_net_poll: Retrieved vfpga device structure. \n");

    // Count the number of packets processed (must not exceed the budget given during registration)
    int packets_processed = 0;

    // Start the main loop for polling the RX-ring buffer and fetching packets from there for further processing in the network stack 
    dbg_info("vfpga_net_poll: Starting packet processing loop with budget %d. \n", budget);

    while(packets_processed < budget && vfpga_rx_has_packet(vfpga)) {
        dbg_info("vfpga_net_poll: Processing packet %d. \n", packets_processed + 1);

        // Fetch the packet from the RX-ring buffer 
        struct sk_buff *skb = vfpga_rx_fetch_packet(vfpga);

        if(!skb) {
            dbg_info("vfpga_net_poll: Didn't get the skb back from the RX-ring (although there should have been one...) \n");
            break; 
        }

        // Pass the packet to the network stack
        dbg_info("vfpga_net_poll: Passing the packet to the network stack. \n");
        skb->protocol = eth_type_trans(skb, vfpga->ndev);
        netif_receive_skb(skb);
        dbg_info("vfpga_net_poll: Packet successfully passed to the network stack. \n");

        // Increment the processed packets counter
        packets_processed++;
        dbg_info("vfpga_net_poll: Finished processing packet %d. \n", packets_processed);
    }

    // Checking if we processed all packets or if we reached the budget limit
    if(packets_processed < budget) {
        // Budget has not been fully used 
        dbg_info("vfpga_net_poll: Processed all available packets (%d), completing NAPI poll. \n", packets_processed);

        // Check if there are no more packets left in the RX-ring buffer
        if(!vfpga_rx_has_packet(vfpga)) {
            dbg_info("vfpga_net_poll: No more packets left in RX-ring buffer, completing NAPI poll. \n");
            napi_complete_done(napi, packets_processed);
        }
    }

    // Return the number of packets processed
    dbg_info("vfpga_net_poll: Finished polling with %d packets processed. \n", packets_processed);
    return packets_processed;   
}

// Function to check if there is a packet available in the RX-ring buffer at the next position 
static bool vfpga_rx_has_packet(struct vfpga_dev *vfpga)
{
    // Calculate pointer to the meta word of the current RX slot
    uint32_t *meta_word_ptr = (uint32_t *)(vfpga->vfpga_net_rx_buf + 
                                           vfpga->rx_buf_head * 6144);

    dbg_info("vfpga_rx_has_packet: Calculated packet address in RX-buffer at %d. \n", *meta_word_ptr);

    // Read raw meta word from DMA buffer
    uint32_t raw_meta = *meta_word_ptr;

    // Decode the meta word
    meta_tag_decoded_t meta;
    meta.possession_flag = (raw_meta >> 31) & 0x1;
    meta.packet_len      = (raw_meta >> 3)  & 0x0FFFFFFF;
    meta.rsvd            = raw_meta & 0x7;

    dbg_info("vfpga_rx_has_packet: Checking RX slot %d, possession_flag=%u\n",
             vfpga->rx_buf_head, meta.possession_flag);

    // Return true if FPGA owns the packet (flag=1)
    return (meta.possession_flag == 1);
}  

// Function to fetch the packet from the RX-ring buffer at the current position and hand it over to the network stack 
static struct sk_buff *vfpga_rx_fetch_packet(struct vfpga_dev *vfpga)
{
    // Get the netdev 
    struct net_device *dev = vfpga->ndev;
    dbg_info("vfpga_rx_fetch_packet: Retrieved net_device structure. \n");

    // Get the pointer to the packet in the RX-buffer 
    void *pkt_addr = vfpga->vfpga_net_rx_buf + vfpga->rx_buf_head * 6144; 
    dbg_info("vfpga_rx_fetch_packet: Calculated packet address in RX-buffer at %p. \n", pkt_addr);

    // Read raw meta word from DMA buffer
    uint32_t raw_meta = *(uint32_t *)pkt_addr;

    // Decode the meta word
    meta_tag_decoded_t meta;
    meta.possession_flag = (raw_meta >> 31) & 0x1;
    meta.packet_len      = (raw_meta >> 3)  & 0x0FFFFFFF;
    meta.rsvd            = raw_meta & 0x7;
    // One more check to ensure the possession flag is set
    if(meta.possession_flag == 0) {
        dbg_info("vfpga_rx_fetch_packet: Possession flag not set, no packet to fetch. \n");
        return NULL;
    }

    // For fetching the actual packet: Read out the packet length from the meta-tag and calculate the packet start address
    size_t pkt_len = meta.packet_len;
    void *actual_pkt_addr = pkt_addr + sizeof(meta_tag_decoded_t);
    dbg_info("vfpga_rx_fetch_packet: Actual packet length is %zu, starting at address %p. \n", pkt_len, actual_pkt_addr);

    // Allocate a new skb for the packet
    struct sk_buff *skb = netdev_alloc_skb(dev, pkt_len); 
    if(!skb) {
        dbg_info("vfpga_rx_fetch_packet: Failed to allocate skb for incoming packet. \n");
        return NULL; 
    }
    dbg_info("vfpga_rx_fetch_packet: Successfully allocated skb at %p. \n", skb);

    // Copy the packet data into the skb
    memcpy(skb_put(skb, pkt_len), actual_pkt_addr, pkt_len);
    dbg_info("vfpga_rx_fetch_packet: Copied packet data into skb. \n");
    skb->protocol = eth_type_trans(skb, dev);
    dbg_info("vfpga_rx_fetch_packet: Set skb protocol to %x. \n", skb->protocol);

    // Clear the possession flag in the meta-tag to indicate the packet has been processed
    meta.possession_flag = 0;
    raw_meta = (meta.possession_flag << 31) |
                    ((meta.packet_len & 0x0FFFFFFF) << 3) |
                    (meta.rsvd & 0x7);
    *(uint32_t *)pkt_addr = raw_meta;
    wmb(); 
    dbg_info("vfpga_rx_fetch_packet: Cleared possession flag in meta-tag. \n");

    // Update the RX buffer head to the next position (wrap around if necessary)
    vfpga->rx_buf_head = (vfpga->rx_buf_head + 1) % 512; 
    dbg_info("vfpga_rx_fetch_packet: Updated RX buffer head to %d. \n", vfpga->rx_buf_head);

    // Return the skb to the caller 
    return skb;
}

// Function for transmitting packets
static netdev_tx_t vfpga_net_xmit(struct sk_buff *skb, struct net_device *dev)
{
    // struct vfpga_dev *fpga = netdev_priv(dev);

    // Increment the counter for outgoing packets and bytes for pushed out packets 
    dev->stats.tx_packets++;
    dev->stats.tx_bytes += skb->len;

    // TO BE IMPLEMENTED: PUSH PACKET TO FPGA FOR TRANSMISSION

    // Free the socket buffer
    dev_kfree_skb(skb);
    return NETDEV_TX_OK; // Return that everything is ok
}

// Struct that points to all the functions of the FPGA-NIC in the driver 
static const struct net_device_ops vfpga_netdev_ops = {
    .ndo_open = vfpga_net_open,
    .ndo_stop = vfpga_net_stop,
    .ndo_start_xmit = vfpga_net_xmit,
}; 

// --------------------------------------------
// Public API for registering the new FPGA-NIC
// --------------------------------------------

// Register the FPGA-NIC
int vfpga_net_register(struct vfpga_dev *vfpga, uint64_t net_mac_addr)
{
    dbg_info("Registering FPGA-NIC - START\n");
    int ret_val;

    // Allocate the net device structure
    dbg_info("Trying to allocate the ethernet device\n");
    vfpga->ndev = alloc_netdev(sizeof(struct vfpga_dev), "slash_%d",
                          NET_NAME_UNKNOWN, ether_setup);
    if (!vfpga->ndev) {
        pr_err("fpga_net: could not allocate net device\n");
        return -ENOMEM;
    }
    dbg_info("Finished allocating the ethernet device\n");

    struct vfpga_dev *priv = netdev_priv(vfpga->ndev);
    *priv = *vfpga;        // copy existing FPGA struct
    priv->ndev = vfpga->ndev; // ensure back-pointer to net_device

    // Set the device operations
    vfpga->ndev->netdev_ops = &vfpga_netdev_ops;

    // Set the MAC address (for simplicity, using a fixed MAC address here)
    uint8_t mac_bytes[ETH_ALEN];
    for (int i = 0; i < ETH_ALEN; i++){
        mac_bytes[i] = (net_mac_addr >> (8 * (ETH_ALEN - 1 - i))) & 0xFF;
    }

    vfpga->ndev->addr_len = ETH_ALEN; 
    if(is_valid_ether_addr(mac_bytes)) {
        dbg_info("Assigned the correct mac_addr for the FPGA. \n");
        ether_addr_copy((uint8_t *)vfpga->ndev->dev_addr, mac_bytes); 
        ether_addr_copy(vfpga->ndev->perm_addr, mac_bytes);
    } else {
        dbg_info("Assigned a random mac_addr for the FPGA. \n");
        eth_hw_addr_random(vfpga->ndev); // Random MAC address for demonstration
    }

    // Bind the NAPI-poll function during registration 
    dbg_info("vfpga_net_register before manually adding: NAPI struct address: %p\n", &vfpga->napi);
    dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    vfpga->napi.dev = vfpga->ndev;
    vfpga->napi.poll = vfpga_net_poll;
    dbg_info("vfpga_net_register after manually adding: NAPI struct address: %p\n", &vfpga->napi);
    dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    netif_napi_add(vfpga->ndev, &vfpga->napi, vfpga_net_poll);
    dbg_info("vfpga_net_register after netif_napi_add: NAPI struct address: %p\n", &vfpga->napi);
    dbg_info("napi.dev=%p, ndev=%p\n", vfpga->napi.dev, vfpga->ndev);
    dbg_info("napi.poll=%p\n", vfpga->napi.poll);
    pr_info("After netif_napi_add: napi.dev=%p napi.poll=%p \n",
        vfpga->napi.dev, vfpga->napi.poll);
    dbg_info("Finished binding NAPI poll function\n");

    // Register the network device
    dbg_info("Trying to register the network device\n");
    ret_val = register_netdev(vfpga->ndev);
    if (ret_val) {
        pr_err("fpga_net: could not register net device\n");
        free_netdev(vfpga->ndev);
        return ret_val;
    }
    dbg_info("Finished registering the network device\n");

    pr_info("fpga_net: device %s registered with MAC %pM\n", vfpga->ndev->name, vfpga->ndev->dev_addr);

    // struct vfpga_dev *priv = netdev_priv(vfpga->ndev);
    *priv = *vfpga;        // copy existing FPGA struct
    priv->ndev = vfpga->ndev; // ensure back-pointer to net_device

    return 0;
}

// Unregister the FPGA-NIC
void vfpga_net_unregister(struct vfpga_dev *vfpga)
{
    dbg_info("Trying to unregister the network device\n");
    if (vfpga->ndev) {
        dbg_info("Found a valid net_device, trying to unregister\n");
        unregister_netdev(vfpga->ndev);
        dbg_info("Finished unregistering the network device\n");
        // free_netdev(fpga->ndev);
        dbg_info("Finished freeing the net_device\n");
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
