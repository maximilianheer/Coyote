`timescale 1ns/1ps
// Registered arbitration guarantees a stalled output never changes request.
module request_arbiter #(
    parameter WIDTH = 128
)(
    input logic clk, rst_n,
    input logic [WIDTH-1:0] a_data, b_data,
    input logic a_valid, b_valid,
    output logic a_ready, b_ready,
    output logic [WIDTH-1:0] out_data,
    output logic out_valid,
    input logic out_ready
);
    logic prefer_b;
    wire available = !out_valid || out_ready;
    wire choose_b = b_valid && (!a_valid || prefer_b);
    assign a_ready = available && !choose_b;
    assign b_ready = available && choose_b;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 0;
            out_data <= 0;
            prefer_b <= 0;
        end else if (available) begin
            out_valid <= a_valid || b_valid;
            if (a_valid || b_valid) begin
                out_data <= choose_b ? b_data : a_data;
                prefer_b <= !choose_b;
            end
        end
    end
endmodule
