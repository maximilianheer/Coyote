`timescale 1ns/1ps
module elastic_fifo_tb;
// 577 payload/keep/last bits plus 6 transaction-ID bits.
localparam WIDTH=583;
logic clk=0;always #2 clk=~clk;
logic rst_n=0,in_valid=0,out_ready=0;
logic [WIDTH-1:0] in_data;wire [WIDTH-1:0] out_data;
wire in_ready,out_valid;wire [5:0] occupancy;
elastic_fifo #(.WIDTH(WIDTH),.DEPTH(32)) dut(.*);
integer sent=0,received=0,cycle=0;
function automatic [WIDTH-1:0] packet(input integer i);
    reg [WIDTH-1:0] data;
    for(integer b=0;b<WIDTH;b++)data[b]=((i*131+b*17+(i>>(b%8)))>>(b%17))&1;
    data[WIDTH-1:577]=6'(i%63+1); // Nonzero TIDs, including wraparound.
    return data;
endfunction
always @(posedge clk)if(rst_n)begin
    cycle=cycle+1;
    if(in_valid && in_ready)sent=sent+1;
    if(out_valid && out_ready)begin
        if(out_data!==packet(received))$fatal(1,"FIFO ordering/TID/payload failure at %0d",received);
        received=received+1;
    end
    if(occupancy>32)$fatal(1,"FIFO overflow");
end
initial begin
    repeat(5)@(negedge clk);rst_n=1;
    while(received<2048)begin
        in_valid=sent<2048 && cycle%7!=0;
        in_data=packet(sent);
        out_ready=cycle%67>35; // Fill, stall, drain and wrap pointers repeatedly.
        @(negedge clk);
        if(cycle>100000)$fatal(1,"FIFO deadlock");
    end
    $display("PASS elastic FIFO 2048 beats, nonzero TIDs, wraparound and backpressure");$finish;
end
endmodule
