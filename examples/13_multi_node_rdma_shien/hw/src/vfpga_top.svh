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

// Maximum cluster size; must match N_MAX_NODES in SW constants.hpp
localparam integer N_MAX_NODES = 10;

///////////////////////////////////////
//       PER-QP INFORMATION         //
/////////////////////////////////////
// SW writes these after every initRDMA() call (setCSR).
// Register layout per peer node i (indexed by node ID):
//   CSR offset 3*i + 0 : QPN        [23:0]   — local Queue Pair Number
//   CSR offset 3*i + 1 : remote_vaddr         — remote buffer virtual address
//   CSR offset 3*i + 2 : local_vaddr          — local  buffer virtual address
//
// Use qp_qpn[i], qp_rvaddr[i], qp_lvaddr[i] in your HW logic below
// when issuing RDMA requests to peer node i.

logic [N_MAX_NODES-1:0][23:0]            qp_qpn;
logic [N_MAX_NODES-1:0][VADDR_BITS-1:0]  qp_rvaddr;
logic [N_MAX_NODES-1:0][VADDR_BITS-1:0]  qp_lvaddr;

// Asserted by SW (via setCSR at offset 3*N_MAX_NODES) once all QP info has been
// written.  Gate any HW-initiated RDMA on this signal.
logic                                     qp_setup_done;

shien_rdma_qp_ctrl_parser #(
    .N_MAX_NODES(N_MAX_NODES)
) inst_qp_ctrl_parser (
    .aclk         (aclk),
    .aresetn      (aresetn),
    .axi_ctrl     (axi_ctrl),
    .qp_qpn       (qp_qpn),
    .qp_rvaddr    (qp_rvaddr),
    .qp_lvaddr    (qp_lvaddr),
    .qp_setup_done(qp_setup_done)
);

///////////////////////////////////////
//     HW-INITIATED RDMA WRITE FSM  //
/////////////////////////////////////
//
// Once SW has set up all QPs and asserted qp_setup_done, this FSM fires a
// single 1 KB RDMA WRITE to peer node RDMA_TARGET (default: node 2).
// The write uses constant-zero payload; no DMA from host memory is required
// because mode=RDMA_MODE_RAW lets the data arrive directly from the fabric.
//
// Nodes that do not have a valid QP to RDMA_TARGET (e.g. node 2 itself, whose
// qp_qpn[2] slot remains zero) skip the send automatically.
//
// Field mapping for sq_wr.data.req_2 (remote descriptor, RDMA_MODE_RAW):
//   opcode = RC_RDMA_WRITE_ONLY  strm = 0  mode = RDMA_MODE_RAW
//   rdma = 1  remote = 1  vfid = 0  pid = qp_qpn[target][PID_BITS-1:0]
//   dest = 0  vaddr = qp_rvaddr[target]  len = RDMA_LEN_BYTES  last = 1
// Field mapping for sq_wr.data.req_1 (local descriptor):
//   vaddr = qp_lvaddr[target]  strm = 0  dest = 0

localparam int RDMA_TARGET    = 2;
localparam int RDMA_LEN_BYTES = 1024;
localparam int RDMA_N_BEATS   = RDMA_LEN_BYTES / (AXI_DATA_BITS / 8); // 16 beats

typedef enum logic [1:0] {
    FSM_IDLE      = 2'd0,
    FSM_SEND_REQ  = 2'd1,
    FSM_SEND_DATA = 2'd2,
    FSM_DONE      = 2'd3
} rdma_fsm_e;

rdma_fsm_e                        rdma_fsm;
logic [$clog2(RDMA_N_BEATS):0]    rdma_beat_cnt;

always_ff @(posedge aclk) begin
    if (!aresetn) begin
        rdma_fsm      <= FSM_IDLE;
        rdma_beat_cnt <= '0;
    end else begin
        case (rdma_fsm)
            FSM_IDLE: begin
                if (qp_setup_done && qp_qpn[RDMA_TARGET] != '0)
                    rdma_fsm <= FSM_SEND_REQ;
            end
            FSM_SEND_REQ: begin
                if (sq_wr.ready)
                    rdma_fsm <= FSM_SEND_DATA;
            end
            FSM_SEND_DATA: begin
                if (axis_rreq_send[0].tready) begin
                    if (rdma_beat_cnt == RDMA_N_BEATS - 1) begin
                        rdma_fsm      <= FSM_DONE;
                        rdma_beat_cnt <= '0;
                    end else begin
                        rdma_beat_cnt <= rdma_beat_cnt + 1;
                    end
                end
            end
            default: ; // FSM_DONE: stay
        endcase
    end
end

///////////////////////////////////////
//     RDMA CONTROL PATH            //
/////////////////////////////////////
//
// During FSM_SEND_REQ: override sq_wr with the HW RDMA WRITE descriptor.
// During FSM_SEND_DATA: hold off SW requests (no new sq_wr).
// Otherwise: forward SW rq_wr/rq_rd as-is (same as original example).

always_comb begin
    // Default: SW passthrough for write path
    sq_wr.valid         = rq_wr.valid;
    rq_wr.ready         = sq_wr.ready;
    sq_wr.data          = rq_wr.data;
    sq_wr.data.strm     = STRM_HOST;
    sq_wr.data.dest     = is_opcode_rd_resp(rq_wr.data.opcode) ? 0 : 1;

    // Read path always passthrough
    sq_rd.valid         = rq_rd.valid;
    rq_rd.ready         = sq_rd.ready;
    sq_rd.data          = rq_rd.data;
    sq_rd.data.strm     = STRM_HOST;
    sq_rd.data.dest     = 1;

    case (rdma_fsm)
        FSM_SEND_REQ: begin
            // Issue the HW RDMA WRITE request; hold off SW
            rq_wr.ready                 = 1'b0;
            sq_wr.valid                 = 1'b1;
            sq_wr.data                  = '0;
            // Remote descriptor (req_2)
            sq_wr.data.opcode     = RC_RDMA_WRITE_ONLY;
            sq_wr.data.strm       = '0;
            sq_wr.data.mode       = RDMA_MODE_RAW;
            sq_wr.data.rdma       = 1'b1;
            sq_wr.data.remote     = 1'b1;
            sq_wr.data.vfid       = '0;
            sq_wr.data.pid        = qp_qpn[RDMA_TARGET][PID_BITS-1:0];
            sq_wr.data.dest       = '0;
            sq_wr.data.vaddr      = qp_rvaddr[RDMA_TARGET];
            sq_wr.data.len        = RDMA_LEN_BYTES;
            sq_wr.data.last       = 1'b1;
        end
        FSM_SEND_DATA: begin
            // Data beats in flight; hold off SW write requests
            rq_wr.ready = 1'b0;
            sq_wr.valid = 1'b0;
        end
        default: ; // FSM_IDLE / FSM_DONE: use defaults above
    endcase
end

/*
 * DATA SIGNALS
 */

// Outgoing RDMA WRITEs: HW-generated data during FSM_SEND_DATA,
// otherwise forwarded from SW host buffer.
always_comb begin
    // Default: SW host data → RDMA send
    axis_rreq_send[0].tvalid = axis_host_recv[0].tvalid;
    axis_rreq_send[0].tdata  = axis_host_recv[0].tdata;
    axis_rreq_send[0].tkeep  = axis_host_recv[0].tkeep;
    axis_rreq_send[0].tlast  = axis_host_recv[0].tlast;
    axis_rreq_send[0].tid    = axis_host_recv[0].tid;
    axis_host_recv[0].tready = axis_rreq_send[0].tready;

    case (rdma_fsm)
        FSM_SEND_REQ: begin
            // Request sent, data not yet flowing; stall both sides
            axis_rreq_send[0].tvalid = 1'b0;
            axis_rreq_send[0].tdata  = '0;
            axis_rreq_send[0].tkeep  = '0;
            axis_rreq_send[0].tlast  = 1'b0;
            axis_rreq_send[0].tid    = '0;
            axis_host_recv[0].tready = 1'b0;
        end
        FSM_SEND_DATA: begin
            // HW-generated constant-zero payload (16 beats of 512 bits)
            axis_rreq_send[0].tvalid = 1'b1;
            axis_rreq_send[0].tdata  = '0;
            axis_rreq_send[0].tkeep  = '1;
            axis_rreq_send[0].tlast  = (rdma_beat_cnt == RDMA_N_BEATS - 1);
            axis_rreq_send[0].tid    = '0;
            axis_host_recv[0].tready = 1'b0;
        end
        default: ; // passthrough
    endcase
end

// Incoming RDMA READ responses (remote → RDMA stack → local host)
`AXISR_ASSIGN(axis_rreq_recv[0], axis_host_send[0])

// Outgoing RDMA READ responses (local host → RDMA stack → remote)
`AXISR_ASSIGN(axis_host_recv[1], axis_rrsp_send[0])

// Incoming RDMA WRITEs (remote → RDMA stack → local host)
`AXISR_ASSIGN(axis_rrsp_recv[0], axis_host_send[1])

// Tie off unused interfaces
always_comb notify.tie_off_m();
always_comb cq_rd.tie_off_s();
always_comb cq_wr.tie_off_s();

// ILA for debugging
ila_perf_rdma inst_ila_perf_rdma (
    .clk(aclk),
    .probe0(axis_host_recv[0].tvalid),      // 1
    .probe1(axis_host_recv[0].tready),      // 1
    .probe2(axis_host_recv[0].tlast),       // 1

    .probe3(axis_host_recv[1].tvalid),      // 1
    .probe4(axis_host_recv[1].tready),      // 1
    .probe5(axis_host_recv[1].tlast),       // 1

    .probe6(axis_host_send[0].tvalid),      // 1
    .probe7(axis_host_send[0].tready),      // 1
    .probe8(axis_host_send[0].tlast),       // 1

    .probe9(axis_host_send[1].tvalid),      // 1
    .probe10(axis_host_send[1].tready),     // 1
    .probe11(axis_host_send[1].tlast),      // 1

    .probe12(sq_wr.valid),                  // 1
    .probe13(sq_wr.ready),                  // 1
    .probe14(sq_rd.valid),                  // 1
    .probe15(sq_rd.ready),                  // 1

    .probe16(qp_setup_done),               // 1
    .probe17(qp_qpn[0]),                   // 24
    .probe18(qp_rvaddr[0]),                // 48  (VADDR_BITS)
    .probe19(qp_lvaddr[0])                 // 48  (VADDR_BITS)
);
