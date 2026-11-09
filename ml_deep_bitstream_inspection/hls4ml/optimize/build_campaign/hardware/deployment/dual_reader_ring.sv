`timescale 1ns/1ps
// Replicated simple-dual-port BRAM: one writer, two independent consumers.
// Release storage on consumption, never merely on speculative prefetch.
module dual_reader_ring #(
    parameter WIDTH = 577,
    parameter ADDR_BITS = 12
)(
    input logic clk, rst_n, clear,
    input logic [WIDTH-1:0] in_data,
    input logic in_valid,
    output logic in_ready,
    output logic [WIDTH-1:0] a_data, b_data,
    output logic a_valid, b_valid,
    input logic a_ready, b_ready,
    output logic [63:0] written, consumed_a, consumed_b, high_water
);
    localparam DEPTH = 1 << ADDR_BITS;
    (* ram_style = "block" *) logic [WIDTH-1:0] memory_a [DEPTH];
    (* ram_style = "block" *) logic [WIDTH-1:0] memory_b [DEPTH];
    // Flow control only needs bounded occupancy, not the 64-bit statistics.
    // Comparing/subtracting frame totals here made a long ready path from the
    // consumers into Coyote's receive FIFO. Keep statistics out of that path.
    logic [ADDR_BITS:0] pending_a, pending_b, unread_a, unread_b;
    logic [ADDR_BITS-1:0] write_address, read_address_a, read_address_b;
    wire [ADDR_BITS:0] used = pending_a > pending_b ? pending_a : pending_b;
    wire write_word = in_valid && in_ready;
    wire consume_a = a_valid && a_ready;
    wire consume_b = b_valid && b_ready;
    wire fetch_a = (!a_valid || a_ready) && unread_a != 0;
    wire fetch_b = (!b_valid || b_ready) && unread_b != 0;
    assign in_ready = pending_a < DEPTH && pending_b < DEPTH && !clear;

    always_ff @(posedge clk) begin
        if (!rst_n || clear) begin
            written <= 0;
            consumed_a <= 0;
            consumed_b <= 0;
            pending_a <= 0;
            pending_b <= 0;
            unread_a <= 0;
            unread_b <= 0;
            write_address <= 0;
            read_address_a <= 0;
            read_address_b <= 0;
            a_valid <= 0;
            b_valid <= 0;
            high_water <= 0;
        end else begin
            case ({write_word, consume_a})
                2'b10: pending_a <= pending_a + 1'b1;
                2'b01: pending_a <= pending_a - 1'b1;
                default: ;
            endcase
            case ({write_word, consume_b})
                2'b10: pending_b <= pending_b + 1'b1;
                2'b01: pending_b <= pending_b - 1'b1;
                default: ;
            endcase
            case ({write_word, fetch_a})
                2'b10: unread_a <= unread_a + 1'b1;
                2'b01: unread_a <= unread_a - 1'b1;
                default: ;
            endcase
            case ({write_word, fetch_b})
                2'b10: unread_b <= unread_b + 1'b1;
                2'b01: unread_b <= unread_b - 1'b1;
                default: ;
            endcase
            if (write_word) begin
                memory_a[write_address] <= in_data;
                memory_b[write_address] <= in_data;
                write_address <= write_address + 1'b1;
                written <= written + 1;
            end
            if (used > high_water) high_water <= used;
            if (consume_a) consumed_a <= consumed_a + 1;
            if (consume_b) consumed_b <= consumed_b + 1;
            if (!a_valid || a_ready) begin
                a_valid <= fetch_a;
                if (fetch_a) begin
                    a_data <= memory_a[read_address_a];
                    read_address_a <= read_address_a + 1'b1;
                end
            end
            if (!b_valid || b_ready) begin
                b_valid <= fetch_b;
                if (fetch_b) begin
                    b_data <= memory_b[read_address_b];
                    read_address_b <= read_address_b + 1'b1;
                end
            end
        end
    end
endmodule
