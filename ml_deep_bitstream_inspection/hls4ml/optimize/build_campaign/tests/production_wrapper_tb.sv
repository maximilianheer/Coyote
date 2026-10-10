`timescale 1ns/1ps
module production_wrapper_tb #(parameter integer FRAME_COUNT=8, parameter integer DRIVER_RESETS=0);
reg ap_clk=0;always #2 ap_clk=~ap_clk;
reg ap_rst_n=0;
reg [511:0] data_in_TDATA=0;
reg [63:0] data_in_TKEEP=0,data_in_TSTRB=0;
reg data_in_TLAST=0,data_in_TVALID=0,data_out_TREADY=0;
wire data_in_TREADY,data_out_TVALID,data_out_TLAST;
wire [511:0] data_out_TDATA;wire [63:0] data_out_TKEEP,data_out_TSTRB;
`ifdef PASSIVE_FIFO_TAPS
wire observer_pixel_write,observer_pixel_read;
`endif
model_wrapper dut(.*);
integer fd,rc,n,frame=0,results=0,wait_cycles=0;
integer cycle=0,frame_start=0;
reg active=0;
reg [31:0] expected_bits;
reg [511:0] payload;
`ifdef PASSIVE_FIFO_TAPS
`include "production_passive_observer.svh"
`endif
always @(posedge ap_clk)begin
    cycle=cycle+1;
    if(active && cycle-frame_start>1000000)
        $fatal(1,"frame stalled frame=%0d bytes=%0d cycles=%0d results=%0d",frame,n,cycle-frame_start,results);
    if(active && (cycle-frame_start)%100000==0)
        $display("PROGRESS production frame=%0d bytes=%0d cycles=%0d results=%0d",frame,n,cycle-frame_start,results);
end
always @(posedge ap_clk) if(ap_rst_n && data_out_TVALID && data_out_TREADY)begin
    // Preserve the production converter: LAST=0, KEEP unspecified; length DMA.
    if(data_out_TDATA[31:0]!==expected_bits || data_out_TLAST!==1'b0)
        $fatal(1,"result mismatch frame=%0d got=%h expected=%h keep=%h last=%b",frame,data_out_TDATA[31:0],expected_bits,data_out_TKEEP,data_out_TLAST);
    results=results+1;
end
task beat(input reg [511:0] data,input reg[63:0] keep,input bit last);
    data_in_TDATA=data;data_in_TKEEP=keep;data_in_TLAST=last;data_in_TVALID=1;
    do @(posedge ap_clk);while(!data_in_TREADY);
    @(negedge ap_clk);data_in_TVALID=0;
endtask
initial begin #400000000;$fatal(1,"wrapper timeout");end
initial begin
    fd=$fopen("rtl_expected.txt","r");if(!fd)$fatal(1,"missing references");
    repeat(100)@(negedge ap_clk);ap_rst_n=1;
    repeat(20000)@(negedge ap_clk);
    // Driver insertion resets an already configured, clocked application.
    // Exercise this separately from the initial configuration reset.
    repeat(DRIVER_RESETS)begin
        ap_rst_n=0;repeat(100)@(negedge ap_clk);ap_rst_n=1;
        repeat(20000)@(negedge ap_clk);
    end
    while(!$feof(fd))begin
        rc=$fscanf(fd,"%d %h\n",n,expected_bits);if(rc!=2)$fatal(1,"bad reference");
        frame_start=cycle;active=1;
        data_out_TREADY=frame%2;
        beat(512'(n),64'hffffffffffffffff,n==0);
        for(integer i=0;i<n;i+=64)begin
            payload=0;
            for(integer b=0;b<64 && i+b<n;b++)payload[b*8+:8]=8'((i+b)*131+(i+b)/11+17);
            if((i/64)%113==0)repeat(3)@(negedge ap_clk);
            beat(payload,n-i>=64?64'hffffffffffffffff:((64'h1<<(n-i))-1),i+64>=n);
        end
        if(!(frame%2))begin
            wait(data_out_TVALID);
            repeat(7)begin
                @(negedge ap_clk);
                if(!data_out_TVALID || data_out_TDATA[31:0]!==expected_bits)
                    $fatal(1,"stalled result frame=%0d valid=%b actual=%h expected=%h",frame,data_out_TVALID,data_out_TDATA[31:0],expected_bits);
            end
            data_out_TREADY=1;
        end
        wait(results==frame+1);
        active=0;
        @(negedge ap_clk);data_out_TREADY=0;
        repeat(20)@(negedge ap_clk);
`ifdef PASSIVE_FIFO_TAPS
        check_passive_frame();
`endif
        $display("PASS production frame=%0d bytes=%0d",frame,n);frame=frame+1;
    end
    if(frame!=FRAME_COUNT)$fatal(1,"missing frames");
    $display("PASS production wrapper frames=%0d driver_resets=%0d",frame,DRIVER_RESETS);$finish;
end
endmodule
