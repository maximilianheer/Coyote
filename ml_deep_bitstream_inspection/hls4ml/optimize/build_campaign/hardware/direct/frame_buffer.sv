`timescale 1ns/1ps
// One complete preprocessed frame. Synchronous BRAM read, held under backpressure.
// raw_complete is the accepted TLAST pulse, including the header of an empty frame.
module frame_buffer #(parameter WIDTH=16, DEPTH=65536,
    parameter ADDR_BITS=$clog2(DEPTH)) (
    input logic clk,rst_n,raw_complete,
    input logic [WIDTH-1:0] in_data,input logic in_valid,output logic in_ready,
    output logic [WIDTH-1:0] out_data,output logic out_valid,input logic out_ready,
    output logic [ADDR_BITS:0] occupancy
);
    (* ram_style="block" *) logic [WIDTH-1:0] mem[0:DEPTH-1];
    logic [ADDR_BITS:0] written,fetched,consumed;
    logic draining,raw_seen;
    assign in_ready=!draining && written<DEPTH;
    assign occupancy=written-consumed;
    always_ff @(posedge clk) begin
        if(in_valid && in_ready && rst_n)mem[written[ADDR_BITS-1:0]]<=in_data;
    end
    always_ff @(posedge clk) begin
        if(!rst_n)begin
            written<=0;fetched<=0;consumed<=0;draining<=0;raw_seen<=0;out_valid<=0;
        end else begin
            if(raw_complete)raw_seen<=1;
            if(in_valid && in_ready)written<=written+1'b1;
            if(!draining && written==DEPTH && raw_seen)draining<=1;
            if(draining && (!out_valid || out_ready))begin
                out_valid<=fetched<DEPTH;
                if(fetched<DEPTH)begin
                    out_data<=mem[fetched[ADDR_BITS-1:0]];
                    fetched<=fetched+1'b1;
                end
            end
            if(out_valid && out_ready)begin
                consumed<=consumed+1'b1;
                if(consumed==DEPTH-1)begin
                    written<=0;fetched<=0;consumed<=0;draining<=0;raw_seen<=0;out_valid<=0;
                end
            end
        end
    end
endmodule
