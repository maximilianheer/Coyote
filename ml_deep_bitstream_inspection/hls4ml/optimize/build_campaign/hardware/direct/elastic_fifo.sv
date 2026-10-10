`timescale 1ns/1ps
// Small elastic FIFO; all larger production CNN buffers retain their depths.
module elastic_fifo #(parameter WIDTH=16, DEPTH=32)(
    input logic clk,rst_n,
    input logic [WIDTH-1:0] in_data, input logic in_valid, output logic in_ready,
    output logic [WIDTH-1:0] out_data, output logic out_valid,input logic out_ready,
    output logic [$clog2(DEPTH+1)-1:0] occupancy
);
    localparam P=$clog2(DEPTH);
    logic [WIDTH-1:0] mem[DEPTH];
    logic [P-1:0] rd,wr;
    wire pop=out_valid && out_ready;
    wire push=in_valid && in_ready;
    assign out_valid=occupancy!=0;
    assign in_ready=occupancy<DEPTH;
    assign out_data=mem[rd];
    always_ff @(posedge clk) begin
        if(!rst_n) begin rd<=0;wr<=0;occupancy<=0;end
        else begin
            if(push) begin mem[wr]<=in_data;wr<=wr==DEPTH-1?0:wr+1'b1;end
            if(pop) rd<=rd==DEPTH-1?0:rd+1'b1;
            case({push,pop})
                2'b10:occupancy<=occupancy+1'b1;
                2'b01:occupancy<=occupancy-1'b1;
                default:begin end
            endcase
        end
    end
endmodule
