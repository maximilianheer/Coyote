/**
 * This file is part of the Coyote <https://github.com/fpgasystems/Coyote>
 *
 * MIT Licence
 * Copyright (c) 2021-2025, Systems Group, ETH Zurich
 * All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:

 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.

 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

import lynxTypes::*;

/**
 * shien_rdma_qp_ctrl_parser
 * @brief Receives per-QP RDMA connection data from SW via the AXI Lite control interface.
 *
 * After SW establishes each pairwise QP (via initRDMA), it writes three values per
 * peer node into this register file, indexed by peer node ID:
 *   - QPN       : local Queue Pair Number (identifies the HW connection context)
 *   - remote_vaddr : virtual address of the remote node's RDMA buffer
 *   - local_vaddr  : virtual address of this node's local RDMA buffer
 *
 * Register map (3 x N_MAX_NODES = 30 64-bit registers):
 *   3*i + 0  (WR): QPN for peer node i          [23:0]
 *   3*i + 1  (WR): Remote vaddr for peer node i  [VADDR_BITS-1:0]
 *   3*i + 2  (WR): Local vaddr for peer node i   [VADDR_BITS-1:0]
 *
 * SW writes these after each initRDMA() call using coyote_thread.setCSR().
 * Slot i == own node ID is unused (a node has no QP to itself).
 *
 * @param[in]  aclk     Clock
 * @param[in]  aresetn  Active-low reset
 * @param[in]  axi_ctrl AXI4-Lite control interface from the host
 * @param[out] qp_qpn      [N_MAX_NODES] Local QPN per peer slot (24-bit)
 * @param[out] qp_rvaddr   [N_MAX_NODES] Remote vaddr per peer slot
 * @param[out] qp_lvaddr   [N_MAX_NODES] Local  vaddr per peer slot
 * @param[out] qp_setup_done Asserted once SW has written all QP info and
 *                           confirmed setup is complete (CSR offset 3*N_MAX_NODES)
 */
module shien_rdma_qp_ctrl_parser #(
    parameter integer N_MAX_NODES = 10
) (
    input  logic        aclk,
    input  logic        aresetn,

    AXI4L.s             axi_ctrl,

    output logic [N_MAX_NODES-1:0][23:0]            qp_qpn,
    output logic [N_MAX_NODES-1:0][VADDR_BITS-1:0]  qp_rvaddr,
    output logic [N_MAX_NODES-1:0][VADDR_BITS-1:0]  qp_lvaddr,
    output logic                                     qp_setup_done
);

/////////////////////////////////////
//          CONSTANTS             //
///////////////////////////////////
// One extra register for the setup-done flag (offset 3*N_MAX_NODES)
localparam integer N_REGS    = 3 * N_MAX_NODES + 1;
localparam integer DONE_REG  = 3 * N_MAX_NODES;
localparam integer ADDR_MSB  = $clog2(N_REGS);
localparam integer ADDR_LSB  = $clog2(AXIL_DATA_BITS/8);
localparam integer AXI_ADDR_BITS = ADDR_LSB + ADDR_MSB;

/////////////////////////////////////
//          REGISTERS             //
///////////////////////////////////
logic [AXI_ADDR_BITS-1:0]           axi_awaddr;
logic                                axi_awready;
logic [AXI_ADDR_BITS-1:0]           axi_araddr;
logic                                axi_arready;
logic [1:0]                          axi_bresp;
logic                                axi_bvalid;
logic                                axi_wready;
logic [AXIL_DATA_BITS-1:0]           axi_rdata;
logic [1:0]                          axi_rresp;
logic                                axi_rvalid;
logic                                aw_en;

logic [N_REGS-1:0][AXIL_DATA_BITS-1:0] ctrl_reg;
logic ctrl_reg_wren;
logic ctrl_reg_rden;

/////////////////////////////////////
//         WRITE PROCESS          //
///////////////////////////////////
assign ctrl_reg_wren = axi_wready && axi_ctrl.wvalid && axi_awready && axi_ctrl.awvalid;

always_ff @(posedge aclk) begin
    if (aresetn == 1'b0) begin
        ctrl_reg <= 0;
    end else begin
        if (ctrl_reg_wren) begin
            // Write the addressed register byte-by-byte (respecting wstrb)
            for (int i = 0; i < (AXIL_DATA_BITS/8); i++) begin
                if (axi_ctrl.wstrb[i]) begin
                    ctrl_reg[axi_awaddr[ADDR_LSB+:ADDR_MSB]][(i*8)+:8] <=
                        axi_ctrl.wdata[(i*8)+:8];
                end
            end
        end
    end
end

/////////////////////////////////////
//         READ PROCESS           //
///////////////////////////////////
// All registers are readable for SW verification / debug.
assign ctrl_reg_rden = axi_arready & axi_ctrl.arvalid & ~axi_rvalid;

always_ff @(posedge aclk) begin
    if (aresetn == 1'b0) begin
        axi_rdata <= 0;
    end else begin
        if (ctrl_reg_rden) begin
            axi_rdata <= ctrl_reg[axi_araddr[ADDR_LSB+:ADDR_MSB]];
        end
    end
end

/////////////////////////////////////
//       OUTPUT ASSIGNMENT        //
///////////////////////////////////
// Unpack the flat register file into per-node arrays.
// Register layout: [3*i+0] = QPN, [3*i+1] = remote_vaddr, [3*i+2] = local_vaddr
generate
    for (genvar i = 0; i < N_MAX_NODES; i++) begin : g_qp_out
        assign qp_qpn[i]    = ctrl_reg[3*i + 0][23:0];
        assign qp_rvaddr[i] = ctrl_reg[3*i + 1][VADDR_BITS-1:0];
        assign qp_lvaddr[i] = ctrl_reg[3*i + 2][VADDR_BITS-1:0];
    end
endgenerate

// SW writes 1 to DONE_REG after all QP info has been written.
assign qp_setup_done = ctrl_reg[DONE_REG][0];

/////////////////////////////////////
//     STANDARD AXI CONTROL       //
///////////////////////////////////
// NOT TO BE EDITED

assign axi_ctrl.awready = axi_awready;
assign axi_ctrl.arready = axi_arready;
assign axi_ctrl.bresp   = axi_bresp;
assign axi_ctrl.bvalid  = axi_bvalid;
assign axi_ctrl.wready  = axi_wready;
assign axi_ctrl.rdata   = axi_rdata;
assign axi_ctrl.rresp   = axi_rresp;
assign axi_ctrl.rvalid  = axi_rvalid;

// awready and awaddr
always_ff @(posedge aclk) begin
    if (aresetn == 1'b0) begin
        axi_awready <= 1'b0;
        axi_awaddr  <= 0;
        aw_en       <= 1'b1;
    end else begin
        if (~axi_awready && axi_ctrl.awvalid && axi_ctrl.wvalid && aw_en) begin
            axi_awready <= 1'b1;
            aw_en       <= 1'b0;
            axi_awaddr  <= axi_ctrl.awaddr;
        end else if (axi_ctrl.bready && axi_bvalid) begin
            aw_en       <= 1'b1;
            axi_awready <= 1'b0;
        end else begin
            axi_awready <= 1'b0;
        end
    end
end

// arready and araddr
always_ff @(posedge aclk) begin
    if (aresetn == 1'b0) begin
        axi_arready <= 1'b0;
        axi_araddr  <= 0;
    end else begin
        if (~axi_arready && axi_ctrl.arvalid) begin
            axi_arready <= 1'b1;
            axi_araddr  <= axi_ctrl.araddr;
        end else begin
            axi_arready <= 1'b0;
        end
    end
end

// bvalid and bresp
always_ff @(posedge aclk) begin
    if (aresetn == 1'b0) begin
        axi_bvalid <= 0;
        axi_bresp  <= 2'b0;
    end else begin
        if (axi_awready && axi_ctrl.awvalid && ~axi_bvalid && axi_wready && axi_ctrl.wvalid) begin
            axi_bvalid <= 1'b1;
            axi_bresp  <= 2'b0;
        end else begin
            if (axi_ctrl.bready && axi_bvalid) begin
                axi_bvalid <= 1'b0;
            end
        end
    end
end

// wready
always_ff @(posedge aclk) begin
    if (aresetn == 1'b0) begin
        axi_wready <= 1'b0;
    end else begin
        if (~axi_wready && axi_ctrl.wvalid && axi_ctrl.awvalid && aw_en) begin
            axi_wready <= 1'b1;
        end else begin
            axi_wready <= 1'b0;
        end
    end
end

// rvalid and rresp
always_ff @(posedge aclk) begin
    if (aresetn == 1'b0) begin
        axi_rvalid <= 0;
        axi_rresp  <= 0;
    end else begin
        if (axi_arready && axi_ctrl.arvalid && ~axi_rvalid) begin
            axi_rvalid <= 1'b1;
            axi_rresp  <= 2'b0;
        end else if (axi_rvalid && axi_ctrl.rready) begin
            axi_rvalid <= 1'b0;
        end
    end
end

endmodule
