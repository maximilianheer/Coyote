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

#include "scenic_rdma.h"
#include <linux/swab.h>
#include <asm/unaligned.h>

// ======-------------------------------------------------------------------------------
//
// FPGA RDMA functions - Exposes Coyote as a IB device to the driver 
//
// ======-------------------------------------------------------------------------------

// Function to calculate the GUID from the MAC once and for all and store it in the vfpga struct
static void scenic_rdma_calculate_guid(struct scenic_rdma_device *scenic_rdma)
{
    dbg_info("scenic_rdma_calculate_guid: Calculating GUID from MAC address - START\n");

    // GUID is formed by inserting 0xFFFE in the middle of the MAC address
    uint8_t mac[ETH_ALEN]; 
    for(int i = 0; i < ETH_ALEN; i++){
        mac[i] = (scenic_rdma->bd_data->net_mac_addr >> (8 * (ETH_ALEN - 1 - i))) & 0xFF;
    }
    dbg_info("scenic_rdma_calculate_guid: Using MAC address %pM for GUID calculation\n", mac);

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

    scenic_rdma->rdma_node_guid = cpu_to_be64(guid);

    dbg_info("scenic_rdma_calculate_guid: Calculated RDMA Node GUID: %016llx\n", scenic_rdma->rdma_node_guid);

    // Construct EUI-64 System Image GUID 
    scenic_rdma->rdma_sys_image_guid = scenic_rdma->rdma_node_guid; 
}

// Function to query the RDMA device attributes 
static int scenic_rdma_query_device(struct ib_device *ibdev, struct ib_device_attr *props, struct ib_udata *uhw)
{
    dbg_info("scenic_rdma_query_device: Querying RDMA device attributes - START\n");

    // Get the scenic_rdma_device structure from the ib_device
    struct scenic_rdma_device *scenic_rdma = ibdev_to_scenic_rdma_dev(ibdev);

    // Reserve enough memory for the props 
    memset(props, 0, sizeof(*props));

    // Basic Identity Information 
    props->fw_ver = 0x01000000;
    props->sys_image_guid = scenic_rdma->rdma_sys_image_guid;
    props->max_mr_size = ~0ull;
    props->page_size_cap = PAGE_SIZE;
    props->vendor_id = 0x02c9; // Xilinx
    props->vendor_part_id = 0x0001; // Custom part ID for C
    props->hw_ver = 0x1;

    // Capabilities
    props->device_cap_flags = IB_DEVICE_MEM_WINDOW | 
                              IB_DEVICE_PORT_ACTIVE_EVENT |
                              IB_DEVICE_RC_RNR_NAK_GEN;

    // Limits 
    props->max_qp = SCENIC_MAX_NUM_QPS;
    props->max_cq = SCENIC_MAX_NUM_CQS;
    props->max_qp_wr = SCENIC_MAX_NUM_QPS / 2; 
    // props->max_sge = 32;
    props->max_cqe = 1024; 
    props->max_mr = 1024;
    props->max_pd = 256;

    return 0; 
}

// Function to query the RDMA port attributes
static int scenic_rdma_query_port(struct ib_device *ibdev, uint32_t port_num, struct ib_port_attr *props)
{
    dbg_info("scenic_rdma_query_port: Querying RDMA port attributes - START\n");

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
static int scenic_rdma_query_gid(struct ib_device *ibdev, uint32_t port_num, int index, union ib_gid *gid)
{
    dbg_info("scenic_rdma_query_gid: Querying RDMA GID - START\n");

    // Get the scenic_rdma_device structure from the ib_device
    struct scenic_rdma_device *scenic_rdma = ibdev_to_scenic_rdma_dev(ibdev); 

    // Construct the GID from the MAC address and IP address
    memset(gid, 0, sizeof(*gid));

    gid->global.subnet_prefix = cpu_to_be64(0xfe80000000000000LL);
    gid->global.interface_id = scenic_rdma->rdma_sys_image_guid;

    return 0; 
}

// Stub for querying the pkey - always return the default pkey 0xFFFF
static int scenic_rdma_query_pkey(struct ib_device *ibdev, uint32_t port_num, uint16_t index, uint16_t *pkey)
{
    dbg_info("scenic_rdma_query_pkey: Querying RDMA PKey - START\n");
    if(index != 0) {
        return -EINVAL; 
    }

    *pkey = 0xFFFF;
    return 0;
}

// Function to get port immutable properties
static int scenic_get_port_immutable(struct ib_device *ibdev, uint32_t port_num, struct ib_port_immutable *immutable)
{
    dbg_info("scenic_get_port_immutable: Getting port immutable properties - START\n");      
    immutable->gid_tbl_len = 32;
    immutable->pkey_tbl_len = 1;

    // 1. RDMA_CORE_PORT_IB_GRH: 
    //    Mandatory. Tells kernel we support Global Routing Headers (IP routing).
    immutable->core_cap_flags = RDMA_CORE_PORT_IBA_IB;

    // 2. Max MAD Size:
    //    RoCE uses IB Management Datagrams (MADs) for some CM operations.
    //    Standard size is 256 bytes (IB_MGMT_MAD_SIZE).
    immutable->max_mad_size = 256;

    return 0; 
}

// Function to query the link layer
static enum rdma_link_layer scenic_rdma_get_link_layer(struct ib_device *ibdev, uint32_t port_num)
{
    dbg_info("scenic_rdma_get_link_layer: Querying RDMA link layer - START\n");

    // Always return Ethernet as link layer - we're doing RoCE, not InfiniBand
    return IB_LINK_LAYER_ETHERNET;
}

// ======-------------------------------------------------------------------------------
//
// FPGA RDMA Resource Management Functions 
//
// ======-------------------------------------------------------------------------------

// Function to 
static int scenic_rdma_alloc_pd(struct ib_pd *pd, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_alloc_pd: Allocating protection domain - START\n");
    struct scenic_pd *scenic_pd = ibpd_to_scenic_pd(pd);
    struct cyt_rdma_alloc_pd_resp resp = {}; 
    static uint32_t next_pdn = 1; // Start PD numbers from 1

    // Empty function: PDs are not enforced in the HW-implementation 
    scenic_pd->pdn = next_pdn++;

    // If userspace asked for it, send the PD number back as response 
    if(udata) {
        dbg_info("scenic_rdma_alloc_pd: Sending PD number %d back to userspace\n", scenic_pd->pdn);
        resp.pdn = scenic_pd->pdn; 

        // Check successful return of copy_to_user
        if (ib_copy_to_udata(udata, &resp, sizeof(resp))) {
            dbg_info("scenic_rdma_alloc_pd: Failed to copy alloc_pd response to userspace\n");
            return -EFAULT;
        }
    } else {
        dbg_info("scenic_rdma_alloc_pd: No userspace data provided, skipping response\n");
    }
    return 0; 
}

// Function to deallocate a protection domain
static int scenic_rdma_dealloc_pd(struct ib_pd *pd, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_dealloc_pd: Deallocating protection domain - START\n");

    // Empty function: PDs are not enforced in the HW-implementation (see above)
    return 0; 
}

// Function to create a completion queue for RDMA 
static int scenic_rdma_create_cq(struct ib_cq *cq, const struct ib_cq_init_attr *attr, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_create_cq: Creating completion queue - START\n");

    // Step 1: Get a pointer to the already allocated vfpga_cq structure
    struct scenic_cq *scenic_cq = ibcq_to_scenic_cq(cq);
    struct cyt_rdma_create_cq_req resp = {};
    static uint32_t next_cqn = 1; // Start CQ numbers from 1

    // Step 2: Assign a hardware CQ Number (CQN)
    scenic_cq->cqn = next_cqn++;

    // Step 3: Userspace handshake (if any)
    if(udata) {
        dbg_info("scenic_rdma_create_cq: Sending CQ number %d back to userspace\n", scenic_cq->cqn);
        resp.cqn = scenic_cq->cqn; 

        // Check successful return of copy_to_user
        if (ib_copy_to_udata(udata, &resp, sizeof(resp))) {
            dbg_info("scenic_rdma_create_cq: Failed to copy create_cq response to userspace\n");
            return -EFAULT;
        }
    } else {
        dbg_info("scenic_rdma_create_cq: No userspace data provided, skipping response\n");
    }

    // Return success at the end of this routine 
    return 0; 
}

// Function to destroy a completion queue for RDMA 
static int scenic_rdma_destroy_cq(struct ib_cq *cq, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_destroy_cq: Destroying completion queue - START\n");

    // Step 1: Get a pointer to the vfpga_cq structure
    struct scenic_cq *scenic_cq = ibcq_to_scenic_cq(cq);
    return 0; 
}


// Function to create a queue pair for RDMA 
static int scenic_rdma_create_qp(struct ib_qp *ibqp, struct ib_qp_init_attr *attr, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_create_qp: Creating queue pair - START\n");

    // STEP 1: Get the context right and allocate all necessary structures
    struct scenic_rdma_device *scenic_rdma = ibdev_to_scenic_rdma_dev(ibqp->device);
    struct scenic_qp *scenic_qp = ibqp_to_scenic_qp(ibqp);
    struct cyt_rdma_create_qp_cmd cmd; 
    int ret; 

    // STEP 2: Validate the requested QP attributes
    if(attr->qp_type != IB_QPT_RC) {
        dbg_info("scenic_rdma_create_qp: Unsupported QP type %d\n", attr->qp_type);
        return -EINVAL;
    }
    if(attr->cap.max_send_wr > SCENIC_MAX_NUM_WRS || attr->cap.max_recv_wr > SCENIC_MAX_NUM_WRS) {
        dbg_info("scenic_rdma_create_qp: Requested WRs exceed maximum (%d)\n", SCENIC_MAX_NUM_WRS);
        return -EINVAL;
    }
    if(attr->cap.max_send_sge > SCENIC_MAX_NUM_SGES || attr->cap.max_recv_sge > SCENIC_MAX_NUM_SGES) {
        dbg_info("scenic_rdma_create_qp: Requested SGEs exceed maximum (%d)\n", SCENIC_MAX_NUM_SGES);
        return -EINVAL;
    }

    // STEP 3: Unpack the QP creation command from userspace (if any)
    if(udata) {
        if(udata->inlen < sizeof(cmd)) {
            dbg_info("scenic_rdma_create_qp: Insufficient userspace data length %zu\n", udata->inlen);
            return -EINVAL;
        }  
        if(ib_copy_from_udata(&cmd, udata, sizeof(cmd))) {
            dbg_info("scenic_rdma_create_qp: Failed to copy create_qp command from userspace\n");
            return -EFAULT;
        }

        // Get the QPN from the incoming command 
        uint32_t user_qpn = cmd.qpn;
        dbg_info("scenic_rdma_create_qp: Received QP creation command with user QPN %u\n", user_qpn);

        // Double-check for potential QPN-collisions 
        if(xa_load(&scenic_rdma->qp_ida.xa, user_qpn)) {
            dbg_info("scenic_rdma_create_qp: QPN %u already in use, cannot create QP\n", user_qpn);
            return -EEXIST;
        }

        // If we passed that test, we're good to go 
        scenic_qp->qpn = user_qpn;
        scenic_qp->state = IB_QPS_RESET;
        ibqp->qp_num = user_qpn;
    }

    // Init the lock of the QP structure
    spin_lock_init(&scenic_qp->lock);

    // Hopefully, this should be it: The kernel should automatically store the QP attributes in the ib_qp structure
    dbg_info("scenic_rdma_create_qp: Created QP with QPN %u\n", scenic_qp->qpn);    

    // Return success at the end of this routine  
    return 0; 
}

// Function to destroy a queue pair for RDMA
static int scenic_rdma_destroy_qp(struct ib_qp *ibqp, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_destroy_qp: Destroying queue pair - START\n");

    // Step 1: Get a pointer to the scenic_qp structure
    struct scenic_qp *scenic_qp = ibqp_to_scenic_qp(ibqp);

    // Step 3: Return success at the end of this routine
    return 0; 
}

// Function to modify the state of the queue pair from the driver function 
static int scenic_rdma_modify_qp(struct ib_qp *ibqp, struct ib_qp_attr *attr, int attr_mask, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_modify_qp: Modifying queue pair - START\n");

    // Step 1: Get a pointer to the scenic_qp structure
    struct scenic_qp *scenic_qp = ibqp_to_scenic_qp(ibqp); 
    enum ib_qp_state old_state, new_state; 

    // Activate the QP lock for safety 
    spin_lock(&scenic_qp->lock);
    old_state = scenic_qp->state;
    new_state = (attr_mask & IB_QP_STATE) ? attr->qp_state : old_state;

    // Use the core helper function to see whether the transition is valid
    if(!ib_modify_qp_is_ok(old_state, new_state, IB_QPT_RC, attr_mask)) {
        dbg_info("scenic_rdma_modify_qp: Invalid QP state transition from %d to %d\n", old_state, new_state);
        goto out;
    }

    // Dependent on the new state, check for compliance of the requested attributes
    switch(new_state) {
        case IB_QPS_INIT:
            if(attr_mask & IB_QP_PORT) {
                dbg_info("scenic_rdma_modify_qp: Moving QP %u to INIT on port %u\n", scenic_qp->qpn, attr->port_num);
                if(attr->port_num < 1 || attr->port_num > ibqp->device->phys_port_cnt) {
                    dbg_info("scenic_rdma_modify_qp: Invalid port number %u for QP %u\n", attr->port_num, scenic_qp->qpn);
                    goto out;
                }
            } else {
                dbg_info("scenic_rdma_modify_qp: Missing port number for moving QP %u to INIT\n", scenic_qp->qpn);
                goto out;
            }  
            break;
        case IB_QPS_RTR:
            if(attr_mask & IB_QP_PATH_MTU) {
                if(attr->path_mtu != IB_MTU_4096) {
                    dbg_info("scenic_rdma_modify_qp: Invalid MTU %d for moving QP %u to RTR\n", attr->path_mtu, scenic_qp->qpn);
                    goto out;
                }
            }
            break; 
        default:
            break;
    }
    out:
    // Store the new state if everything went well
    scenic_qp->state = new_state;
    dbg_info("scenic_rdma_modify_qp: QP %u state changed from %d to %d\n", scenic_qp->qpn, old_state, new_state);

    // Release the QP lock before returning
    spin_unlock(&scenic_qp->lock);

    // Step 6: Return success at the end of this routine
    return 0; 
}

// Function to register a user memory region for RDMA 
static struct ib_mr *scenic_rdma_reg_user_mr(struct ib_pd *pd, uint64_t start, uint64_t length, uint64_t virt_addr, int access_flags, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_reg_user_mr: Registering user memory region - START\n");

    // Allocate a memory region structure
    struct scenic_mr *scenic_mr = kzalloc(sizeof(*scenic_mr), GFP_KERNEL);
    struct cyt_rdma_reg_mr_resp resp = {};
    if(!scenic_mr) {
        dbg_info("scenic_rdma_reg_user_mr: Failed to allocate memory for memory region\n");
        return ERR_PTR(-ENOMEM);
    }

    // Missing: Call to the pinning function for the transmitted virtual address -> needs to be implemented 

    // Set the ib_mr fields
    scenic_mr->ibmr.lkey = 0x1000; // Who the fuck cares about security anyways? 
    scenic_mr->ibmr.rkey = 0x1000; // I certainly don't. 

    // Send back userdata 
    if (udata)
    {
        dbg_info("scenic_rdma_reg_user_mr: Sending lkey and rkey back to userspace. \n"); 
        resp.lkey = scenic_mr->ibmr.lkey; 
        resp.rkey = scenic_mr->ibmr.rkey;
        dbg_info("scenic_rdma_reg_user_mr: lkey %d and rkey %d \n", resp.lkey, resp.rkey); 

        // Check successful return of copy_to_user
        if(ib_copy_to_udata(udata, &resp, sizeof(resp))) {
            dbg_info("scenic_rdma_reg_user_mr: Failed to copy response to userspace\n");
        }
    } else {
        dbg_info("scenic_rdma_reg_user_mr: No userdata provided.\n"); 
    }
    

    // To be implemented later on 
    return &scenic_mr->ibmr;
}

// Functio to deregister a memory region for RDMA 
static int scenic_rdma_dereg_mr(struct ib_mr *mr, struct ib_udata *udata)
{
    struct scenic_mr *scenic_mr = ibmr_to_scenic_mr(mr); 

    // Release the pinned memory (not so sure about this bs)
    if(scenic_mr->umem) {
        // ib_umem_release(scenic_mr->umem);
        dbg_info("scenic_rdma_dereg_mr: Released pinned user memory region.\n");
    }

    // Free the memory region structure
    kfree(scenic_mr);

    return 0;
}

// Function to allocate a user context for RDMA: This is where we pass the mem regs and stuff from kernel space to user space 
static int scenic_rdma_alloc_ucontext(struct ib_ucontext *ucontext, struct ib_udata *udata)
{
    dbg_info("scenic_rdma_alloc_ucontext: Allocating user context - START\n");

    // Get the context right: 
    // struct scenic_rdma_device *scenic_rdma = ibdev_to_scenic_rdma_dev(ucontext->device);
    struct scenic_ucontext *scenic_ucontext = ibucxt_to_scenic_ucontext(ucontext);
    dbg_info("scenic_rdma_alloc_ucontext: scenic ucontext structure located at %p\n", scenic_ucontext);
    struct cyt_rdma_alloc_ucontext_resp resp = {};
    dbg_info("scenic_rdma_alloc_ucontext: Preparing alloc_ucontext response structure at %p\n", &resp);

    // STEP 1: Validation -> Making sure we're talking to the userspace app anyway
    if(!udata) {
        dbg_info("scenic_rdma_alloc_ucontext: No userspace data provided!\n");
        return -EINVAL;
    }
    dbg_info("scenic_rdma_alloc_ucontext: Userspace data provided at %p\n", udata);

    // STEP 2: Initialize the driver context 
    INIT_LIST_HEAD(&scenic_ucontext->qp_list);
    dbg_info("scenic_rdma_alloc_ucontext: Initialized QP list head at %p\n", &scenic_ucontext->qp_list);
    spin_lock_init(&scenic_ucontext->ctx_lock);
    dbg_info("scenic_rdma_alloc_ucontext: Initialized context lock\n");
    scenic_ucontext->hw_vmid = 0; // To be implemented later

    // STEP 3: Prepare the response structure
    resp.max_qp = SCENIC_MAX_NUM_QPS;
    resp.max_cq = SCENIC_MAX_NUM_CQS;
    // resp.vfpga_ctrl_reg = vfpga->vfpga_cnfg_phys_addr + SCENIC_CTRL_USER_OFFS;
    // resp.vfpga_cnfg_reg = vfpga->vfpga_cnfg_avx_phys_addr;
    // resp.vfpga_wb_reg = vfpga->wb_phys_addr;

    dbg_info("scenic_rdma_alloc_ucontext: Prepared alloc_ucontext response structure:\n");

    // STEP 4: Copy the response structure to userspace
    if(ib_copy_to_udata(udata, &resp, sizeof(resp))) {
        dbg_info("scenic_rdma_alloc_ucontext: Failed to copy alloc_ucontext response to userspace\n");
        return -EFAULT;
    }

    dbg_info("scenic_rdma_alloc_ucontext: Successfully copied alloc_ucontext response to userspace\n");

    // To be implemented later on 
    return 0; 
}

// Function to deallocate a user context for RDMA 
static void scenic_rdma_dealloc_ucontext(struct ib_ucontext *ucontext)
{
    dbg_info("scenic_rdma_dealloc_ucontext: Deallocating user context - START\n");
}

// Function to handle mmap calls from userspace for RDMA
static int scenic_rdma_mmap(struct ib_ucontext *ucontext, struct vm_area_struct *vma)
{
    dbg_info("scenic_rdma_mmap: Handling mmap call from userspace - START\n");

    // Reimplement the mmap-function fro vfpga_ops.c here, for which we need the vfpga_dev structure 
    // struct vfpga_dev *device = ibdev_to_vfpga_dev(ucontext->device);

    // Now copy the functionality from vfpga_dev_mmap here
    vma->vm_page_prot = pgprot_noncached(vma->vm_page_prot);

    return 0; 
    
        // Memory map user registers (CSR) in vFPGAs; the ones parsed from axi_ctrl interface in the vFPGA
    /* if (vma->vm_pgoff == MMAP_CTRL) {
        dbg_info(
            "fpga dev. %d, memory mapping user ctrl region at %llx of size %x\n",
            device->id, device->vfpga_cnfg_phys_addr + SCENIC_CTRL_USER_OFFS, SCENIC_CTRL_USER_SIZE
        );
        int ret_val = remap_pfn_range(
            vma, 
            vma->vm_start, 
            (device->vfpga_cnfg_phys_addr + SCENIC_CTRL_USER_OFFS) >> PAGE_SHIFT,
            SCENIC_CTRL_USER_SIZE, 
            vma->vm_page_prot
        );
        if (ret_val) {
            pr_warn("remap_pfn_range failed for user ctrl region, ret_val: %d\n", ret_val);
            return -EIO;
        } else {
            return 0;
        }
    }

    // Memory map vFPGA config (non-AVX) region (cnfg_slave)
    if (vma->vm_pgoff == MMAP_CNFG) {
        dbg_info(
            "fpga dev. %d, memory mapping config region at %llx of size %x\n",
            device->id, device->vfpga_cnfg_phys_addr + SCENIC_CTRL_CNFG_OFFS, SCENIC_CTRL_CNFG_SIZE
        );
        int ret_val = remap_pfn_range(
            vma, 
            vma->vm_start, 
            (device->vfpga_cnfg_phys_addr + SCENIC_CTRL_CNFG_OFFS) >> PAGE_SHIFT,
            SCENIC_CTRL_CNFG_SIZE, 
            vma->vm_page_prot
        );
        if (ret_val) {
            pr_warn("remap_pfn_range failed for shell config region, ret_val: %d\n", ret_val);
            return -EIO;
        } else {
            return 0;
        }
    }

    // Memory map shell config (AVX) region (cnfg_slave_avx)
    if (vma->vm_pgoff == MMAP_CNFG_AVX) {
        dbg_info(
            "fpga dev. %d, memory mapping config AVX region at %llx of size %x\n",
            device->id, device->vfpga_cnfg_avx_phys_addr, SCENIC_CTRL_CNFG_AVX_SIZE
        );
        int ret_val = remap_pfn_range(
            vma, 
            vma->vm_start, 
            device->vfpga_cnfg_avx_phys_addr >> PAGE_SHIFT,
            SCENIC_CTRL_CNFG_AVX_SIZE, 
            vma->vm_page_prot
        );
        if (ret_val) {
            pr_warn("remap_pfn_range failed for shell config AVX region, ret_val: %d\n", ret_val);
            return -EIO;
        } else {
            return 0;
        }
    }

    // Memory map writeback region
    if (vma->vm_pgoff == MMAP_WB) {
        set_memory_uc((uint64_t) device->wb_addr_virt, N_WB_PAGES);
        dbg_info(
            "fpga dev. %d, memory mapping writeback regions at %llx of size %lx\n",
            device->id, device->wb_phys_addr, WB_SIZE
        );
        int ret_val = remap_pfn_range(
            vma, 
            vma->vm_start, 
            (device->wb_phys_addr) >> PAGE_SHIFT,
            WB_SIZE, 
            vma->vm_page_prot
        );
        if (ret_val) {
            pr_warn("remap_pfn_range failed for writeback region, ret_val: %d\n", ret_val);
            return -EIO;
        } else {
            return 0;
        }
    }

    pr_warn("requested unknown memory mapping for vFPGA device\n");
    return -EINVAL; */ 
}


// Struct that points to all the ib_device functions of the FPGA-RDMA in the driver 
static const struct ib_device_ops scenic_ibdev_ops = {
    .owner = THIS_MODULE,
    .driver_id = RDMA_DRIVER_UNKNOWN,

    INIT_RDMA_OBJ_SIZE(ib_ucontext, scenic_ucontext, ibucontext),
    INIT_RDMA_OBJ_SIZE(ib_pd, scenic_pd, ibpd),
    INIT_RDMA_OBJ_SIZE(ib_cq, scenic_cq, ibcq),
    INIT_RDMA_OBJ_SIZE(ib_qp, scenic_qp, ibqp),
    // INIT_RDMA_OBJ_SIZE(ib_mr, vfpga_mr, ib

    // Device / Port functions 
    .query_device = scenic_rdma_query_device, 
    .query_port = scenic_rdma_query_port, 
    .query_gid = scenic_rdma_query_gid,
    .query_pkey = scenic_rdma_query_pkey,
    .get_port_immutable = scenic_get_port_immutable,
    .get_link_layer = scenic_rdma_get_link_layer,

    // Ressources management functions
    .alloc_pd = scenic_rdma_alloc_pd,
    .dealloc_pd = scenic_rdma_dealloc_pd,   
    .create_cq = scenic_rdma_create_cq,
    .destroy_cq = scenic_rdma_destroy_cq,
    .create_qp = scenic_rdma_create_qp,
    .modify_qp = scenic_rdma_modify_qp,
    .destroy_qp = scenic_rdma_destroy_qp,
    .reg_user_mr = scenic_rdma_reg_user_mr,
    .dereg_mr = scenic_rdma_dereg_mr,

    // Userspace Glue 
    .alloc_ucontext = scenic_rdma_alloc_ucontext,
    .dealloc_ucontext = scenic_rdma_dealloc_ucontext,
    .mmap = scenic_rdma_mmap, 

    // Userspace function, kept NULL for our use case 
    .post_send = NULL,
    .poll_cq = NULL, 

    // Advanced features, kept NULL for now 
    .create_srq = NULL,
    .resize_cq = NULL

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
int scenic_rdma_register(struct scenic_rdma_device *scenic_rdma)
{
    dbg_info("scenic_rdma_register: Registering FPGA-RDMA - START\n");

    // Step 1: Call the function to calculate the GUIDs from the MAC address
    dbg_info("scenic_rdma_register: Calculate GUID\n");
    scenic_rdma_calculate_guid(scenic_rdma);

    // Step 2: Allocate the ib_device structure
    struct scenic_ib_device *scenic_ib_dev;
    struct ib_device *ib_dev;
    dbg_info("scenic_rdma_register: Allocate ib_device\n");
    scenic_ib_dev = ib_alloc_device(scenic_ib_device, ib_dev);
    if (!scenic_ib_dev) {
        dbg_info("scenic_rdma_register: Failed to allocate ib_device structure\n");
        return -ENOMEM;
    }

    // Step 3: Set reverse pointers from ib_device to vfpga_dev
    dbg_info("scenic_rdma_register: Exchanging all the pointers\n");
    ib_dev = &scenic_ib_dev->ib_dev;
    scenic_ib_dev->rdma_dev = scenic_rdma;
    scenic_rdma->scenic_ib_dev = scenic_ib_dev;

    // Step 4: Set important fields in the ib_device structure to inform the RDMA core about our driver
    ib_dev->node_type = RDMA_NODE_IB_CA;
    ib_dev->phys_port_cnt = 1; 
    /* ib_dev->driver_cq_len = sizeof(struct vfpga_cq); // Size of our custom CQ structure
    ib_dev->driver_qp_len = sizeof(struct vfpga_qp); // Size of our custom QP structure */ 
    dbg_info("scenic_rdma_register: Set GUID \n");
    ib_dev->node_guid = scenic_rdma->rdma_node_guid;
    dbg_info("scenic_rdma_register: Set name \n");
    memcpy(ib_dev->node_desc, "SCENIC", sizeof("SCENIC")); // Optional: Name your device

    // Set the PCI-Dev for the ib_device to avoid the kernel nullpointer 
    dbg_info("scenic_rdma_register: Set PCI device \n");
    ib_dev->dev.parent = &scenic_rdma->bd_data->pci_dev->dev;

    // Set the ABI-version 
    ib_dev->uverbs_cmd_mask |= (1ull << IB_USER_VERBS_CMD_GET_CONTEXT);
    ib_dev->num_comp_vectors = 1;

    // Set the dev_ops
    ib_set_device_ops(ib_dev, &scenic_ibdev_ops);
    dbg_info("vfpga_rdma_register: Register node type and port count \n");

    // Register the ib_device with the RDMA core
    dbg_info("vfpga_rdma_register: Calling ib_register_device \n");
    int ret = ib_register_device(ib_dev, "scenic_ib%d", NULL);
    if (ret) {
        dbg_info("vfpga_rdma_register: Failed to register ib_device with RDMA core\n");
        ib_dealloc_device(ib_dev);
        return ret;
    }
    dbg_info("vfpga_rdma_register: Returning successfully \n");
    // Step 5: Initialize the ib_device structure
    return 0; 
}

// Unregister the FPGA-RDMA 
void scenic_rdma_deregister(struct scenic_rdma_device *scenic_rdma)
{
    dbg_info("vfpga_rdma_unregister: Unregistering FPGA-RDMA - START\n");

    dbg_info("vfpga_rdma_unregister: Calling ib_unregister_device \n");
    ib_unregister_device(&scenic_rdma->scenic_ib_dev->ib_dev);
    dbg_info("vfpga_rdma_unregister: Deallocating ib_device \n");
    ib_dealloc_device(&scenic_rdma->scenic_ib_dev->ib_dev);
    dbg_info("vfpga_rdma_unregister: Returning successfully \n");
}