`timescale 1ns/1ps
// Credits retire only after BOTH all response beats and the independent CQ.
// Native Coyote segments larger descriptors into PMTU-sized memory operations.
module reader_window #(parameter TRACKING = 128)(
    input logic clk, rst_n, start, busy,
    input logic [8:0] window_limit,
    input logic descriptor_valid,
    output logic descriptor_ready,
    input logic [63:0] descriptor_address,
    input logic [31:0] descriptor_bytes,
    output logic request_valid,
    input logic request_ready,
    output logic [63:0] request_address,
    output logic [31:0] request_bytes,
    input logic response_valid,
    output logic response_ready,
    input logic [511:0] response_data,
    output logic word_valid,
    input logic word_ready,
    output logic [511:0] word_data,
    input logic completion,
    output logic idle, error,
    output logic [63:0] issued, received_words, completed, response_requests,
    output logic [63:0] requested_bytes, peak_outstanding,
    output logic [63:0] request_stalls, credit_stalls, response_backpressure
);
    localparam INDEX_BITS = $clog2(TRACKING);
    logic [10:0] beats [TRACKING];
    logic [10:0] beat_index;
    wire [63:0] retired = response_requests < completed ? response_requests : completed;
    wire [63:0] outstanding = issued - retired;
    wire credit = outstanding < {55'b0, window_limit};
    wire request_fire = request_valid && request_ready;
    wire response_fire = word_valid && word_ready;
    wire descriptor_ok = descriptor_bytes > 0 && descriptor_bytes <= 65536 &&
                         descriptor_address[5:0] == 0;
    wire [10:0] head_beats = beats[response_requests[INDEX_BITS-1:0]];
    assign request_valid = descriptor_valid && busy && credit && descriptor_ok;
    assign descriptor_ready = request_ready && busy && credit && descriptor_ok;
    assign request_address = descriptor_address;
    assign request_bytes = descriptor_bytes;
    assign word_valid = response_valid && busy && response_requests < issued;
    assign response_ready = word_ready && busy && response_requests < issued;
    assign word_data = response_data;
    assign idle = issued == response_requests && issued == completed;

    always_ff @(posedge clk) begin
        if (!rst_n || start) begin
            issued <= 0;
            received_words <= 0;
            completed <= 0;
            response_requests <= 0;
            requested_bytes <= 0;
            peak_outstanding <= 0;
            request_stalls <= 0;
            credit_stalls <= 0;
            response_backpressure <= 0;
            beat_index <= 0;
            error <= 0;
        end else begin
            if (busy && descriptor_valid && !descriptor_ok) error <= 1;
            if (busy && descriptor_valid && !credit) credit_stalls <= credit_stalls + 1;
            if (request_valid && !request_ready) request_stalls <= request_stalls + 1;
            if (busy && response_valid && !response_ready)
                response_backpressure <= response_backpressure + 1;
            if (outstanding + 64'(request_fire) > peak_outstanding)
                peak_outstanding <= outstanding + 64'(request_fire);
            if (request_fire) begin
                issued <= issued + 1;
                requested_bytes <= requested_bytes + {32'b0, descriptor_bytes};
                beats[issued[INDEX_BITS-1:0]] <= 11'((descriptor_bytes + 63) >> 6);
            end
            if (response_fire) begin
                received_words <= received_words + 1;
                if (beat_index + 1 == head_beats) begin
                    response_requests <= response_requests + 1;
                    beat_index <= 0;
                end else begin
                    beat_index <= beat_index + 1;
                end
            end
            if (completion) begin
                if (completed >= issued + 64'(request_fire)) error <= 1;
                completed <= completed + 1;
            end
            if (busy && (window_limit == 0 || window_limit > TRACKING)) error <= 1;
        end
    end
endmodule
