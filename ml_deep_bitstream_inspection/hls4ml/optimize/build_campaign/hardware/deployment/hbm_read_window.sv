`timescale 1ns/1ps
// Single-beat read credit lasts until BOTH ordered data and CQ have returned.
module hbm_read_window #(
    parameter LIMIT = 32
)(
    input logic clk, rst_n, start, busy,
    input logic address_valid,
    output logic address_ready,
    input logic [63:0] address,
    output logic request_valid,
    input logic request_ready,
    output logic [63:0] request_address,
    input logic response_valid,
    output logic response_ready,
    input logic [511:0] response_data,
    output logic word_valid,
    input logic word_ready,
    output logic [511:0] word_data,
    input logic completion,
    output logic idle, error,
    output logic [63:0] issued, received, completed
);
    wire [63:0] retired = received < completed ? received : completed;
    wire credit = issued - retired < LIMIT;
    assign request_valid = address_valid && busy && credit;
    assign request_address = address;
    assign address_ready = request_ready && busy && credit;
    assign word_valid = response_valid && busy && received < issued;
    assign word_data = response_data;
    assign response_ready = word_ready && busy && received < issued;
    assign idle = issued == received && issued == completed;

    always_ff @(posedge clk) begin
        if (!rst_n || start) begin
            issued <= 0;
            received <= 0;
            completed <= 0;
            error <= 0;
        end else begin
            if (request_valid && request_ready) issued <= issued + 1;
            if (word_valid && word_ready) received <= received + 1;
            if (completion) begin
                if (completed >= issued) error <= 1;
                completed <= completed + 1;
            end
        end
    end
endmodule
