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
    logic [63:0] fetched_a, fetched_b;
    wire [63:0] released = consumed_a < consumed_b ? consumed_a : consumed_b;
    wire [63:0] used = written - released;
    assign in_ready = used < DEPTH && !clear;

    always_ff @(posedge clk) begin
        if (!rst_n || clear) begin
            written <= 0;
            consumed_a <= 0;
            consumed_b <= 0;
            fetched_a <= 0;
            fetched_b <= 0;
            a_valid <= 0;
            b_valid <= 0;
            high_water <= 0;
        end else begin
            if (in_valid && in_ready) begin
                memory_a[written[ADDR_BITS-1:0]] <= in_data;
                memory_b[written[ADDR_BITS-1:0]] <= in_data;
                written <= written + 1;
            end
            if (used > high_water) high_water <= used;
            if (a_valid && a_ready) consumed_a <= consumed_a + 1;
            if (b_valid && b_ready) consumed_b <= consumed_b + 1;
            if (!a_valid || a_ready) begin
                a_valid <= fetched_a < written;
                if (fetched_a < written) begin
                    a_data <= memory_a[fetched_a[ADDR_BITS-1:0]];
                    fetched_a <= fetched_a + 1;
                end
            end
            if (!b_valid || b_ready) begin
                b_valid <= fetched_b < written;
                if (fetched_b < written) begin
                    b_data <= memory_b[fetched_b[ADDR_BITS-1:0]];
                    fetched_b <= fetched_b + 1;
                end
            end
        end
    end
endmodule
