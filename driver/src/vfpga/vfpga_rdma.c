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
    uint8_t *mac = vfpga->ndev->dev_addr;

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
    props->node_guid = vfpga->rdma_node_guid;
    return 0; 
}

// Struct that points to all the ib_device functions of the FPGA-RDMA in the driver 
static const struct ib_device_ops vfpga_ibdev_ops = {
    .owner = THIS_MODULE,
    .driver_id = RDMA_DRIVER_ID_UNKNOWN,

    // Device / Port functions 
    .query_device = vfpga_rdma_query_device, 
    .query_port = vfpga_rdma_query_port, 
    .query_gid = vfpga_rdma_query_gid,
    .get_link_layer = vfpga_rdma_get_link_layer,

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
    .mmap = vfpga_rdma_mmap
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
    vfpga_ib_dev = ib_alloc_device(struct vfpga_ib_device, ib_dev);
    if (!vfpga_ib_dev) {
        dbg_info("vfpga_rdma_register: Failed to allocate ib_device structure\n");
        return -ENOMEM;
    }

    // Step 3: Set reverse pointers from ib_device to vfpga_dev
    ib_dev = &vfpga_ib_dev->ib_dev;
    vfpga_ib_dev->vfpga_dev = vfpga;
    vfpga->vfpga_ib_dev = ib_dev;


    // Step 4: Initialize the ib_device structure
    return 0; 
}

// Unregister the FPGA-RDMA 
int vfpga_rdma_unregister(struct vfpga_dev *vfpga)
{
    dbg_info("vfpga_rdma_unregister: Unregistering FPGA-RDMA - START\n");
    return 0;
}