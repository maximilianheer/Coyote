`timescale 1ns/1ps
module direct_control_tb;
parameter VARIANT=7;
logic clk=0;always #2 clk=~clk;
logic rst_n=0;
logic [63:0] awaddr=0,araddr=0,wdata=0,rdata;
logic [7:0] wstrb=0;
logic awvalid=0,wvalid=0,bready=1,arvalid=0,rready=1;
wire awready,wready,bvalid,arready,rvalid;wire [1:0] bresp,rresp;
logic in_valid=0,in_ready=1,in_last=0;logic [511:0] in_data=0;logic [63:0] in_keep=-1;
logic out_valid=0,out_ready=1,pp_valid=0,pp_ready=1,cnn_valid=0,cnn_ready=1;
logic [5:0] fifo_occupancy=0;
logic read_complete=0,write_complete=0,result_valid=0,result_record_valid=1;
logic [31:0] result_bits=0;logic [63:0] result_trial=0;
wire busy;wire [63:0] trial_id;
direct_control #(.VARIANT(VARIANT)) dut(.*);
task wr(input integer regid,input logic[63:0] data);
    @(negedge clk);awaddr=regid*8;awvalid=1;
    do @(posedge clk);while(!awready);
    @(negedge clk);awvalid=0;
    repeat(2)@(negedge clk);
    wdata=data;wstrb=8'hff;wvalid=1;
    do @(posedge clk);while(!wready);
    @(negedge clk);wvalid=0;
    wait(bvalid);@(negedge clk);
endtask
task rd(input integer regid,output logic[63:0] data);
    @(negedge clk);araddr=regid*8;arvalid=1;
    do @(posedge clk);while(!arready);
    @(negedge clk);arvalid=0;wait(rvalid);data=rdata;
endtask
task beat(input logic[511:0] data,input bit last);
    @(negedge clk);in_data=data;in_last=last;in_valid=1;
    out_valid=(VARIANT==9);
    @(negedge clk);in_valid=0;out_valid=0;
endtask
logic[63:0] value,origin;
initial begin #10000000;$fatal(1,"control timeout");end
initial begin
    repeat(5)@(negedge clk);rst_n=1;
    for(integer frame=0;frame<3;frame++)begin
        wr(1,frame==0?0:frame==1?1:65);wr(2,frame+100);wr(0,1);
        if(!busy)$fatal(1,"not armed");
        rd(6,origin);rd(5,value);if(value<=origin)$fatal(1,"counter latch");
        // Split AXI-Lite writes, input gaps, and blocked ingress.
        repeat(3)@(negedge clk);
        beat(frame==0?0:frame==1?1:65,frame==0);
        if(frame>0)beat(512'h123,frame==1);
        if(frame==2)beat(512'h456,1);
        @(negedge clk);read_complete=1;write_complete=(VARIANT==9);
        @(negedge clk);read_complete=0;write_complete=0;
        if(VARIANT==7)begin
            for(integer i=0;i<65536;i++)begin
                pp_valid=1;cnn_valid=1;
                @(negedge clk);
            end
            pp_valid=0;cnn_valid=0;
        end
        if(VARIANT!=8)begin
            result_bits=(frame==0?32'h00000000:frame==1?32'hbf800000:32'h3f800000);
            result_trial=frame+100;result_valid=1;
            @(negedge clk);result_valid=0;
        end
        rd(0,value);if(value!=2)$fatal(1,"bad completion %h variant=%d",value,VARIANT);
        rd(15,value);if(value<=origin)$fatal(1,"missing decision");
        rd(20,value);if(value!=(frame==0?1:frame==1?2:3))$fatal(1,"beat count");
        rd(7,value);if(value[0]!=(frame>0) || value[1]!=(frame>0) || !value[8])$fatal(1,"payload/ack events %h",value);
        if(VARIANT==7)begin
            rd(27,value);if(value!=65536)$fatal(1,"producer count");
            rd(28,value);if(value!=65536)$fatal(1,"consumer count");
        end
        if(VARIANT!=8)begin
            rd(26,value);if(value[32]!=(frame!=1))$fatal(1,"verdict threshold");
        end
    end
    if(VARIANT==9)begin
        wr(1,0);wr(2,200);wr(0,1);beat(0,1);
        result_trial=199;result_valid=1;@(negedge clk);result_valid=0;
        rd(0,value);if(!value[2] || value[1] || !value[0])$fatal(1,"stale GPU verdict accepted");
    end
    $display("PASS direct control variant=%0d",VARIANT);$finish;
end
endmodule
