`timescale 1ns/1ps
// Diagnostic ABI: signature, tick, mode, bytes, requests, completions,
// first/last payload ticks and stalled cycles. Mode writes require quiescence.
module diagnostic_control #(
    parameter ADDR_BITS = 64,
    parameter DATA_BITS = 64
)(
    input logic clk, rst_n,
    input logic [ADDR_BITS-1:0] awaddr, araddr,
    input logic awvalid, wvalid, bready, arvalid, rready,
    input logic [DATA_BITS-1:0] wdata,
    input logic [DATA_BITS/8-1:0] wstrb,
    output logic awready, wready, bvalid, arready, rvalid,
    output logic [1:0] bresp, rresp,
    output logic [DATA_BITS-1:0] rdata,
    input logic request, complete, payload, blocked,
    input logic [63:0] keep,
    output logic card_mode
);
    logic have_aw, have_w;
    logic [ADDR_BITS-1:0] address;
    logic [DATA_BITS-1:0] value;
    logic [DATA_BITS/8-1:0] strobes;
    logic [63:0] tick, bytes_seen, requests, completions;
    logic [63:0] first_tick, last_tick, stalls;
    logic seen;
    logic [6:0] valid_bytes;
    wire commit = have_aw && have_w && !bvalid;

    always_comb begin
        valid_bytes = 0;
        for (int lane = 0; lane < 64; lane++)
            valid_bytes = valid_bytes + {6'b0, keep[lane]};
    end

    assign awready = !have_aw && !bvalid;
    assign wready = !have_w && !bvalid;
    assign arready = !rvalid;
    assign bresp = 0;
    assign rresp = 0;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            have_aw <= 0;
            have_w <= 0;
            bvalid <= 0;
            rvalid <= 0;
            rdata <= 0;
            address <= 0;
            value <= 0;
            strobes <= 0;
            card_mode <= 0;
            tick <= 0;
            bytes_seen <= 0;
            requests <= 0;
            completions <= 0;
            first_tick <= 0;
            last_tick <= 0;
            stalls <= 0;
            seen <= 0;
        end else begin
            tick <= tick + 1;
            if (awvalid && awready) begin
                address <= awaddr;
                have_aw <= 1;
            end
            if (wvalid && wready) begin
                value <= wdata;
                strobes <= wstrb;
                have_w <= 1;
            end
            if (bvalid && bready) bvalid <= 0;
            if (commit) begin
                have_aw <= 0;
                have_w <= 0;
                bvalid <= 1;
                if (address[11:3] == 2 && strobes[0] &&
                    requests == completions && !request && !payload)
                    card_mode <= value[0];
            end
            if (rvalid && rready) rvalid <= 0;
            if (arvalid && arready) begin
                rvalid <= 1;
                case (araddr[11:3])
                    0: rdata <= 64'h4e45544400010000;
                    1: rdata <= tick;
                    2: rdata <= {63'b0, card_mode};
                    3: rdata <= bytes_seen;
                    4: rdata <= requests;
                    5: rdata <= completions;
                    6: rdata <= first_tick;
                    7: rdata <= last_tick;
                    8: rdata <= stalls;
                    default: rdata <= 0;
                endcase
            end
            if (request) requests <= requests + 1;
            if (complete) completions <= completions + 1;
            if (blocked) stalls <= stalls + 1;
            if (payload) begin
                bytes_seen <= bytes_seen + {57'b0, valid_bytes};
                if (!seen) first_tick <= tick;
                seen <= 1;
                last_tick <= tick;
            end
        end
    end
endmodule
