module streaming_control_tb;
localparam VARIANT=6, INSTRUMENT=1;
logic clk=0;always #5 clk=~clk;
logic rst_n=0;
logic [63:0] awaddr=0,araddr=0,wdata=0,rdata,source_addr;
logic awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
logic [7:0] wstrb=8'hff;
logic awready,wready,bvalid,arready,rvalid,request_valid,request_ready=0,read_complete=0,busy;
logic [1:0] bresp,rresp;
logic [31:0] source_bytes,source_pid,result_bits=0;
logic in_valid=0,in_ready=0,result_valid=0;
logic [2:0] phase=0;
logic [3:0] stage_events=0;
logic [31:0] produced_tokens=0;
benchmark_control #(.VARIANT(VARIANT), .INSTRUMENT(INSTRUMENT)) dut(.*);

task automatic wr(input int idx,input logic [63:0] value,input bit data_first=0);
 if(data_first) begin
  @(negedge clk);wdata=value;wvalid=1;
  do @(posedge clk); while(!wready);
  @(negedge clk);wvalid=0;
  repeat(2) @(posedge clk);
  @(negedge clk);awaddr=64'(idx*8);awvalid=1;
  do @(posedge clk); while(!awready);
  @(negedge clk);awvalid=0;
 end else begin
  @(negedge clk);awaddr=64'(idx*8);awvalid=1;
  do @(posedge clk); while(!awready);
  @(negedge clk);awvalid=0;
  repeat(2) @(posedge clk);
  @(negedge clk);wdata=value;wvalid=1;
  do @(posedge clk); while(!wready);
  @(negedge clk);wvalid=0;
 end
 wait(bvalid);repeat(2) @(posedge clk);
 @(negedge clk);bready=1;
 @(negedge clk);bready=0;
endtask

task automatic rd(input int idx,output logic[63:0] value);
 @(negedge clk);araddr=64'(idx*8);arvalid=1;
 do @(posedge clk); while(!arready);
 @(negedge clk);arvalid=0;
 wait(rvalid);value=rdata;
 repeat(2) begin @(posedge clk);assert(rvalid && rdata==value) else $fatal;end
 @(negedge clk);rready=1;
 @(negedge clk);rready=0;
endtask
logic [63:0] value;
initial begin
 #100000;$fatal(1,"timeout");
end
initial begin
 repeat(3) @(negedge clk);rst_n=1;
 wr(2,192);
 // Same-cycle, early, and late acknowledgement; repeat frames with toggled events.
 for (int order=0; order<3; order++) begin
  wr(0,1); assert(busy && request_valid) else $fatal;
  repeat(3) @(negedge clk);
  request_ready=1; @(negedge clk); request_ready=0;
  in_ready=1; repeat(3) @(negedge clk); // starvation
  in_valid=1; @(negedge clk); // header
  stage_events[0]=!stage_events[0]; produced_tokens=1;
  @(negedge clk); // payload one
  stage_events[2]=!stage_events[2]; in_ready=0;
  repeat(4) @(negedge clk); // input backpressure, concurrent preprocessing/CNN
  in_ready=1; @(negedge clk); // final payload
  in_valid=0; in_ready=0; produced_tokens=65536;
  stage_events[1]=!stage_events[1];
  if(order==0) read_complete=1;
  @(negedge clk);read_complete=0;
  repeat(3) @(negedge clk);stage_events[3]=!stage_events[3];
  repeat(2) @(negedge clk);result_bits=32'h3f800000+order;result_valid=1;
  if(order==1) read_complete=1;
  @(negedge clk);result_valid=0;read_complete=0;
  if(order==2) begin
   assert(busy && dut.done && !dut.ack_seen) else $fatal(1,"late ack lost");
   repeat(5) @(negedge clk);read_complete=1;
   @(negedge clk);read_complete=0;
  end
  assert(!busy && dut.done && dut.ack_seen) else $fatal;
  assert(dut.starve==3 && dut.blocked_input==4 && dut.beats==3) else $fatal(1,"stall counters");
  assert(dut.payload_first==5 && dut.payload_last==10) else $fatal(1,"payload timestamps");
  assert(dut.event_tick[0]==5 && dut.event_tick[2]==6 && dut.event_tick[1]==11) else $fatal(1,"overlapping stages");
  assert(dut.event_tick[3]==15 && dut.decision_tick==17) else $fatal(1,"publication");
  rd(27,value);assert(value==65536) else $fatal;
  rd(20,value);assert(value==239) else $fatal;
  rd(14,value);assert(value==32'h3f800000+order) else $fatal;
  rd(19,value);assert(value==(order==0 ? 11 : order==1 ? 17 : 23)) else $fatal(1,"ack order %0d tick %0d",order,value);
 end
 // Empty payload: only a header; never invent a payload timestamp.
 wr(2,64);wr(0,1);request_ready=1;
 @(negedge clk);request_ready=0;in_valid=1;in_ready=1;
 @(negedge clk);in_valid=0;in_ready=0;read_complete=1;result_valid=1;
 @(negedge clk);read_complete=0;result_valid=0;
 assert(!dut.payload_seen && dut.payload_first==0 && dut.payload_last==0) else $fatal;
 $display("PASS streaming counters, concurrent stages, stalls, empty payload, and all acknowledgement orders");$finish;
end
endmodule
