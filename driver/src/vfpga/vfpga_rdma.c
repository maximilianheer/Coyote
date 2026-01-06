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

#include "vfpga_rdma.h"
#include <linux/swab.h>
#include <asm/unaligned.h>

// ======-------------------------------------------------------------------------------
//
// FPGA RDMA functions - Exposes Coyote as a IB device to the driver 
//
// ======-------------------------------------------------------------------------------

// Function to calculate the GUID from the MAC once and for all and store it in the vfpga struct
static void vfpga_rdma_calculate_guid(struct vfpga_dev *vfpga)
{
    dbg_info("vfpga_rdma_calculate_guid: Calculating GUID from MAC address - START\n");

    // GUID is formed by inserting 0xFFFE in the middle of the MAC address
    const uint8_t *mac = vfpga->ndev->dev_addr;

    // Construct EUI-64 Node GUID 
    uint64_t guid = 0; 
    guid |= ((uint64_t)mac[0] << 56);
    guid |= ((uint64_t)mac[1] << 48);
    guid |= ((uint64_t)mac[2] << 40);
    guid |= ((uint64_t)0xFF << 32);
    guid |= ((uint64_t)0xFE << 24);
    guid |= ((uint64_t)mac[3] << 16);
    guid |= ((uint64_t)mac[4] << 8);
    guid |= ((uint64_t)mac[5] << 0);

    vfpga->rdma_node_guid = cpu_to_be64(guid);

    dbg_info("vfpga_rdma_calculate_guid: Calculated RDMA Node GUID: %016llx\n", vfpga->rdma_node_guid);

    // Construct EUI-64 System Image GUID 
    vfpga->rdma_sys_image_guid = vfpga->rdma_node_guid; 
}

// Function to query the RDMA device attributes 
static int vfpga_rdma_query_device(struct ib_device *ibdev, struct ib_device_attr *props, struct ib_udata *uhw)
{
    dbg_info("vfpga_rdma_query_device: Querying RDMA device attributes - START\n");

    // Get the vfpga_dev structure from the ib_device
    struct vfpga_dev *vfpga = ibdev_to_vfpga_dev(ibdev); 

    // Reserve enough memory for the props 
    memset(props, 0, sizeof(*props));

    // Device attributes #1: Identity 
    props->sys_image_guid = vfpga->rdma_sys_image_guid;
    return 0; 
}

// Function to query the RDMA port attributes
static int vfpga_rdma_query_port(struct ib_device *ibdev, uint32_t port_num, struct ib_port_attr *props)
{
    dbg_info("vfpga_rdma_query_port: Querying RDMA port attributes - START\n");

    // Reserve enough memory for the props 
    memset(props, 0, sizeof(*props));

    // Port attributes #1: Identity 
    props->lid = 0; // No LID in RoCE
    props->state = IB_PORT_ACTIVE;
    props->phys_state = IB_PORT_PHYS_STATE_LINK_UP;
    props->port_cap_flags = IB_UVERBS_PCF_CM_SUP | 
                            IB_UVERBS_PCF_REINIT_SUP | 
                            IB_UVERBS_PCF_DEVICE_MGMT_SUP | 
                            IB_UVERBS_PCF_VENDOR_CLASS_SUP | 
                            IB_UVERBS_PCF_NOTICE_SUP;    
    props->gid_tbl_len = 1; // Only one GID supported
    props->max_mtu = IB_MTU_4096;
    props->active_mtu = IB_MTU_4096;
    props->pkey_tbl_len = 1; // Only one PKey supported
    props->bad_pkey_cntr = 0;
    props->qkey_viol_cntr = 0;
    props->sm_lid = 0;
    props->subnet_timeout = 0;
    props->init_type_reply = 0;
    props->active_width = IB_WIDTH_4X;
    props->active_speed = IB_SPEED_EDR;

    // Further required attributes according to gemini
    props->max_msg_sz = 0x80000000; 
    props->pkey_tbl_len = 1;
    return 0; 
}

// Function query the RDMA GID 
static int vfpga_rdma_query_gid(struct ib_device *ibdev, uint32_t port_num, int index, union ib_gid *gid)
{
    dbg_info("vfpga_rdma_query_gid: Querying RDMA GID - START\n");

    // Get the vfpga_dev structure from the ib_device
    struct vfpga_dev *vfpga = ibdev_to_vfpga_dev(ibdev); 

    // Construct the GID from the MAC address and IP address
    memset(gid, 0, sizeof(*gid));

    gid->global.subnet_prefix = cpu_to_be64(0xfe80000000000000LL);
    gid->global.interface_id = vfpga->rdma_sys_image_guid;

    return 0; 
}

// Function to query the link layer
/* static enum ib_link_layer vfpga_rdma_get_link_layer(struct ib_device *ibdev, uint32_t port_num)
{
    dbg_info("vfpga_rdma_get_link_layer: Querying RDMA link layer - START\n");

    // Always return Ethernet as link layer - we're doing RoCE, not InfiniBand
    return IB_LINK_LAYER_ETHERNET;
} */ 

// ======-------------------------------------------------------------------------------
//
// FPGA RDMA Resource Management Functions 
//
// ======-------------------------------------------------------------------------------

// Function to allocate a protection domain
static int vfpga_rdma_alloc_pd(struct ib_pd *pd, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_alloc_pd: Allocating protection domain - START\n");

    // Empty function: PDs are not enforced in the HW-implementation 
    return 0; 
}

// Function to deallocate a protection domain
static int vfpga_rdma_dealloc_pd(struct ib_pd *pd, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_dealloc_pd: Deallocating protection domain - START\n");

    // Empty function: PDs are not enforced in the HW-implementation (see above)
    return 0; 
}

// Function to create a completion queue for RDMA 
static int vfpga_rdma_create_cq(struct ib_cq *cq, const struct ib_cq_init_attr *attr, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_create_cq: Creating completion queue - START\n");

    // Step 1: Get a pointer to the already allocated vfpga_cq structure
    struct vfpga_cq *vfpga_cq = ibcq_to_vfpga_cq(cq);

    // Step 2: Initialize the vfpga_cq structure
    spin_lock_init(&vfpga_cq->lock);
    INIT_LIST_HEAD(&vfpga_cq->cq_list);

    // Step 3: Userspace handshake (if any)
    if(udata) {
        struct cyt_rdma_create_cq_resp resp = {
            .cqn = 0, // For simplicity, always return CQ number 0
            .entries = attr->cqe
        }; 

        // Check successful return of copy_to_user
        if (ib_copy_to_udata(udata, &resp, sizeof(resp))) {
            dbg_info("vfpga_rdma_create_cq: Failed to copy create_cq response to userspace\n");
            return -EFAULT;
        }
    }

    // Return success at the end of this routine 
    return 0; 
}

// Function to destroy a completion queue for RDMA 
static int vfpga_rdma_destroy_cq(struct ib_cq *cq, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_destroy_cq: Destroying completion queue - START\n");

    // Step 1: Get a pointer to the vfpga_cq structure
    struct vfpga_cq *vfpga_cq = ibcq_to_vfpga_cq(cq);
    unsigned long flags;

    // Step 2: Safety check: There should be no QPs attached to this CQ anymore 
    spin_lock_irqsave(&vfpga_cq->lock, flags);
    if (!list_empty(&vfpga_cq->cq_list)) {
        pr_warn("vfpga_rdma_destroy_cq: WARNING - Destroying CQ that still has QPs attached to it.\n");
    }
    spin_unlock_irqrestore(&vfpga_cq->lock, flags);

    // That's all -> memory handling is done automatically for us 

    // Return success at the end of this routine 
    return 0; 
}


// Function to create a queue pair for RDMA 
static int vfpga_rdma_create_qp(struct ib_qp *ibqp, struct ib_qp_init_attr *attr, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_create_qp: Creating queue pair - START\n");

    // STEP 1: Get the context right 
    struct vfpga_dev *vfpga = ibdev_to_vfpga_dev(ibqp->device);
    struct vfpga_qp *vfpga_qp = ibqp_to_vfpga_qp(ibqp);
    // struct cyt_create_qp_resp resp = {}; 
    // struct cyt_create_qp_req req; 
    int ret; 

    // STEP 2: Initialize the helper structures 
    spin_lock_init(&vfpga_qp->lock);
    INIT_LIST_HEAD(&vfpga_qp->cq_node);

    // STEP 3: Assign a hardware QP Number (QPN) -> QUESTION: Can we use random QPNs or do we need to construct them ourselves? 
    ret = ida_alloc_max(&vfpga->qp_ida, VFPGA_MAX_NUM_QPS - 1, GFP_KERNEL);
    if (ret < 0) {
        dbg_info("vfpga_rdma_create_qp: Failed to allocate QP number\n");
        return ret; 
    }

    // Store the new QPN in the vfpga_qp structure and the generic ib_qp structure
    vfpga_qp->qpn = ret; 
    ibqp->qp_num = ret;

    // STEP 4: Userspace handshake (if any)
    if (udata) {
        // Do something -> to be implemented later on 
        // IDEA: We transmit the entire memory layout at once, including the doorbells and buffer addresses. Seems to make more sense tbh. 
    }

    // STEP 5: Link to the Virtual Completion Queue 
    if(ibqp->send_cq){
        // Obtain the vfpga_cq from the Queue Pair's send_cq
        struct vfpga_cq *vfpga_cq = ibcq_to_vfpga_cq(ibqp->send_cq);
        unsigned long flags;

        // Use the lock and append the QP to the CQ's list
        spin_lock_irqsave(&vfpga_cq->lock, flags);
        list_add_tail(&vfpga_qp->cq_node, &vfpga_cq->cq_list);
        spin_unlock_irqrestore(&vfpga_cq->lock, flags);
    }

    // STEP 6: Return Data to userspace 
    /* if(udata) {
        if(ib_copy_to_udata(udata, &resp, sizeof(resp))) {
            dbg_info("vfpga_rdma_create_qp: Failed to copy create_qp response to userspace\n");
            ret = - EFAULT;
            goto err_unlink;
        }
    } */ 

    // Return success at the end of this routine  
    return 0; 
}

// Function to modify the state of the queue pair from the driver function 
static int vfpga_rdma_modify_qp(struct ib_qp *ibqp, struct ib_qp_attr *attr, int attr_mask, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_modify_qp: Modifying queue pair - START\n");

    // STEP 1: Get the context right based on the given arguments 
    // struct vfpga_dev *vfpga = ibdev_to_vfpga_dev(ibqp->device);
    struct vfpga_qp *vfpga_qp = ibqp_to_vfpga_qp(ibqp);
    enum ib_qp_state cur_state, next_state; 
    int ret = 0; 
    unsigned long flags; 

    // STEP 2: Spin up the lock for this QP
    spin_lock_irqsave(&vfpga_qp->lock, flags);

    // STEP 3: Resolve the states (current and next)
    cur_state = (attr_mask & IB_QP_STATE) ? attr->cur_qp_state : vfpga_qp->qp_state;
    next_state = (attr_mask & IB_QP_STATE) ? attr->qp_state : cur_state;

    // STEP 4: Validate the state transition with helper functions 
    if(!ib_modify_qp_is_ok(cur_state, next_state, vfpga_qp->ibqp.qp_type, attr_mask)) {
        ret = -EINVAL;
        goto out; 
    }

    // STEP 5: Hardware Interaction -> This function is moved to the userspace library to stay consistent

    // STEP 6: Update the kernel software state so that we can query the current state of the QP later on 
    if(attr_mask & IB_QP_STATE) {
        vfpga_qp->qp_state = next_state;
    }

    if(attr_mask & IB_QP_ACCESS_FLAGS) {
        vfpga_qp->qp_access_flags = attr->qp_access_flags;
    }

    // Store the port number if provided 
    if(attr_mask & IB_QP_PORT) {
        vfpga_qp->port_num = attr->port_num;
    }

    // STEP 7: Store MTU if provided for later querying
    if(attr_mask & IB_QP_PATH_MTU) {
        vfpga_qp->path_mtu = attr->path_mtu;
    }

    // STEP 8: Clean up and return success
    out:

    spin_unlock_irqrestore(&vfpga_qp->lock, flags);
    return ret;
}

// Function to destroy a queue pair for RDMA 
static int vfpga_rdma_destroy_qp(struct ib_qp *ibqp, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_destroy_qp: Destroying queue pair - START\n");

    // STEP 1: Get the context right
    struct vfpga_dev *vfpga = ibdev_to_vfpga_dev(ibqp->device);
    struct vfpga_qp *vfpga_qp = ibqp_to_vfpga_qp(ibqp);
    unsigned long flags;
    int ret = 0;    

    // STEP 2: Unlink from the CQ if linked
    if(ibqp->send_cq){
        struct vfpga_cq *vfpga_cq = ibcq_to_vfpga_cq(ibqp->send_cq);

        spin_lock_irqsave(&vfpga_cq->lock, flags);
        // Check if we are actually in the list before deleting 
        if(!list_empty(&vfpga_qp->cq_node)) {
            list_del(&vfpga_qp->cq_node);
        }
        spin_unlock_irqrestore(&vfpga_cq->lock, flags);
    }

    // STEP 3: Tell the FPGA to stop DMA'ing -> Will still put this to userspace for consistency. 

    // STEP 4: Release the QPN 
    ida_free(&vfpga->qp_ida, vfpga_qp->qpn);

    // STEP 5: Free the QP structure 
    kfree(vfpga_qp);

    // Step 6: Return success at the end of this routine
    return ret; 
}

// Function to register a user memory region for RDMA 
static struct ib_mr *vfpga_rdma_reg_user_mr(struct ib_pd *pd, uint64_t start, uint64_t length, uint64_t virt_addr, int access_flags, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_reg_user_mr: Registering user memory region - START\n");

    // To be implemented later on 
    return 0;
}

// Functio to deregister a memory region for RDMA 
static int vfpga_rdma_dereg_mr(struct ib_mr *mr, struct ib_udata *udata)
{
    dbg_info("vfpga_rdma_dereg_mr: Deregistering memory region - START\n");

    // To be implemented later on 
    return 0;
}

// Struct that points to all the ib_device functions of the FPGA-RDMA in the driver 
static const struct ib_device_ops vfpga_ibdev_ops = {
    .owner = THIS_MODULE,
    .driver_id = RDMA_DRIVER_UNKNOWN,

    // Device / Port functions 
    .query_device = vfpga_rdma_query_device, 
    .query_port = vfpga_rdma_query_port, 
    .query_gid = vfpga_rdma_query_gid,
    // .get_link_layer = vfpga_rdma_get_link_layer,

    // Ressources management functions
    .alloc_pd = vfpga_rdma_alloc_pd,
    .dealloc_pd = vfpga_rdma_dealloc_pd,   
    .create_cq = vfpga_rdma_create_cq,
    .destroy_cq = vfpga_rdma_destroy_cq,
    .create_qp = vfpga_rdma_create_qp,
    .modify_qp = vfpga_rdma_modify_qp,
    .destroy_qp = vfpga_rdma_destroy_qp,
    .reg_user_mr = vfpga_rdma_reg_user_mr,
    .dereg_mr = vfpga_rdma_dereg_mr,

    // Userspace Glue 
    .alloc_ucontext = vfpga_rdma_alloc_ucontext,
    .dealloc_ucontext = vfpga_rdma_dealloc_ucontext,
    .mmap = vfpga_rdma_mmap, 

    /** 
    .size_cq = sizeof(struct vfpga_cq),
    .size_qp = sizeof(struct vfpga_qp),
    .size_mr = sizeof(struct vfpga_mr),
    .size_pd = sizeof(struct vfpga_pd)
    */ 
}; 

// --------------------------------------------
// Public API for registering the new FPGA-RDMA
// --------------------------------------------

// Register the FPGA-RDMA
int vfpga_rdma_register(struct vfpga_dev *vfpga)
{
    dbg_info("vfpga_rdma_register: Registering FPGA-RDMA - START\n");

    // Step 1: Call the function to calculate the GUIDs from the MAC address
    vfpga_rdma_calculate_guid(vfpga);

    // Step 2: Allocate the ib_device structure 
    struct vfpga_ib_device *vfpga_ib_dev;
    struct ib_device *ib_dev;
    vfpga_ib_dev = ib_alloc_device(vfpga_ib_device, ib_dev);
    if (!vfpga_ib_dev) {
        dbg_info("vfpga_rdma_register: Failed to allocate ib_device structure\n");
        return -ENOMEM;
    }

    // Step 3: Set reverse pointers from ib_device to vfpga_dev
    ib_dev = &vfpga_ib_dev->ib_dev;
    vfpga_ib_dev->vfpga_dev = vfpga;
    vfpga->vfpga_ib_dev = vfpga_ib_dev;

    // Step 4: Set important fields in the ib_device structure to inform the RDMA core about our driver
    ib_set_device_ops(ib_dev, &vfpga_ibdev_ops);
    ib_dev->node_type = RDMA_NODE_RNIC;
    ib_dev->phys_port_cnt = 1; 
    /* ib_dev->driver_cq_len = sizeof(struct vfpga_cq); // Size of our custom CQ structure
    ib_dev->driver_qp_len = sizeof(struct vfpga_qp); // Size of our custom QP structure */ 
    ib_dev->node_guid = vfpga->rdma_node_guid;
    memcpy(ib_dev->node_desc, "SCENIC", sizeof("SCENIC")); // Optional: Name your device

    // Step 5: MMAP the control registers that are needed for setting up RDMA QPs 

    // Register the ib_device with the RDMA core
    int ret = ib_register_device(ib_dev, "scenic_ib%d", NULL);
    if (ret) {
        dbg_info("vfpga_rdma_register: Failed to register ib_device with RDMA core\n");
        ib_dealloc_device(ib_dev);
        return ret;
    }

    // Step 5: Initialize the ib_device structure
    return 0; 
}

// Unregister the FPGA-RDMA 
void vfpga_rdma_deregister(struct vfpga_dev *vfpga)
{
    dbg_info("vfpga_rdma_unregister: Unregistering FPGA-RDMA - START\n");
}