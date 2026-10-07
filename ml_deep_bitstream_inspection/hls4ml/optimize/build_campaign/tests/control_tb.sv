module control_tb #(parameter integer VARIANT=1, parameter bit INSTRUMENT=(VARIANT!=2));
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
 rd(15,value);assert(value==((VARIANT==6 ? 64'h4342595400020000 : 64'h4342595400010000) | 64'(VARIANT))) else $fatal;
 wr(1,64'h12340000);wr(2,128,1);wr(3,3);
 rd(1,value);assert(value==64'h12340000) else $fatal;
 wr(0,1);
 assert(request_valid && busy && source_bytes==128 && source_pid==3) else $fatal;
 repeat(3) @(negedge clk);
 request_ready=1;@(negedge clk);request_ready=0;phase=1;in_ready=1;
 repeat(4) @(negedge clk);
 in_valid=1;repeat(2) @(negedge clk);in_valid=0;in_ready=0;phase=2;
 repeat(5) @(negedge clk);phase=3;read_complete=1;
 @(negedge clk);read_complete=0;result_bits=32'h3f800000;result_valid=1;
 @(negedge clk);result_valid=0;phase=0;
 rd(0,value);assert(value[2:0]==3'b010) else $fatal;
 rd(12,value);assert(value==(INSTRUMENT ? 2 : 0)) else $fatal;
 rd(13,value);assert(value>10 && value<30) else $fatal;
 rd(14,value);assert(value==64'h3f800000) else $fatal;
 rd(8,value);assert(value==((INSTRUMENT && VARIANT!=6) ? 5 : 0)) else $fatal;
 rd(19,value);assert(value>0) else $fatal;
 wr(0,1,1);assert(busy && request_valid) else $fatal;
 rd(12,value);assert(value==0) else $fatal;
 $display("PASS variant=%0d instrument=%0d AXI-Lite, ABI, DMA start, counters, result, repeated trial", VARIANT, INSTRUMENT);$finish;
end
endmodule
