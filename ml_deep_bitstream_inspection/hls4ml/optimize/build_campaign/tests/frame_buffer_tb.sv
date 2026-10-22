`timescale 1ns/1ps
module frame_buffer_tb;
localparam DEPTH=65536;
logic clk=0;always #2 clk=~clk;
logic rst_n=0,raw_complete=0,in_valid=0,in_ready,out_valid,out_ready=0;
logic [15:0] in_data=0,out_data;logic [16:0] occupancy;
integer received=0,base=0,ticks=0;bit checking=0,filled=0,raw_done=0;
logic [15:0] held;bit stalled=0;
frame_buffer dut(.*);
always @(posedge clk)begin
 ticks=ticks+1;
 if(rst_n)begin
  if(out_valid && (!filled || !raw_done))$fatal(1,"premature drain");
  if(stalled && (!out_valid || out_data!==held))$fatal(1,"unstable backpressure");
  if(out_valid && out_ready && checking)begin
   if(out_data!==16'(base+received))$fatal(1,"data mismatch index=%0d",received);
   received=received+1;
  end
  stalled=out_valid && !out_ready;held=out_data;
 end else stalled=0;
end
always @(negedge clk)out_ready=rst_n && ticks%7!=0 && ticks%7!=1;
task reset;
 @(negedge clk);rst_n=0;in_valid=0;raw_complete=0;checking=0;
 repeat(4)@(negedge clk);
 received=0;filled=0;raw_done=0;rst_n=1;
 repeat(4)@(negedge clk);
 if(out_valid || occupancy!=0)$fatal(1,"reset failed");
endtask
task raw_end;
 @(negedge clk);raw_complete=1;raw_done=1;
 @(negedge clk);raw_complete=0;
endtask
task fill(input integer count,input integer start);
 base=start;received=0;checking=1;
 for(integer i=0;i<count;i++)begin
  @(negedge clk);in_data=16'(start+i);in_valid=1;
  do @(posedge clk);while(!in_ready);
 end
 @(negedge clk);in_valid=0;
 if(count==DEPTH)filled=1;
endtask
task complete_frame(input integer start,input bit early);
 if(early)raw_end();
 fill(DEPTH,start);
 if(!early)begin repeat(20)@(negedge clk);if(out_valid)$fatal(1,"raw tail was not awaited");raw_end();end
 wait(received==DEPTH);repeat(5)@(negedge clk);
 if(occupancy!=0 || out_valid)$fatal(1,"drain failed");
 filled=0;raw_done=0;checking=0;
endtask
initial begin
 reset();complete_frame(123,0);complete_frame(234,1);
 fill(1234,400);reset();complete_frame(567,1);
 raw_end();fill(DEPTH,800);wait(received>=321);reset();complete_frame(900,0);
 $display("PASS frame buffer: late raw tail, early raw completion, stalls, consecutive frames, reset during fill and drain");$finish;
end
initial begin #10000000;$fatal(1,"timeout");end
endmodule
