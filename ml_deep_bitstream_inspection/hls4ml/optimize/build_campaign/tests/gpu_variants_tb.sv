`timescale 1ns/1ps
module gpu_variants_tb;
 top_elaboration dut();
 always #2 dut.aclk=~dut.aclk;
 integer cycle=0,frame=0,n=0,total=0,forwarded=0,requests=0;
 integer dma_delay=-1,response_delay=7;
 logic [63:0] dma_addr=0;
 logic corrupt=0,checking=0;
 integer variant;
 function automatic [511:0] packet(input integer index);
  reg [511:0] value;
  for(integer b=0;b<64;b++)value[b*8+:8]=8'(index*131+b*7+frame);
  if(index==0)value[63:0]=64'(n);
  return value;
 endfunction
 always @(posedge dut.aclk)begin
  cycle=cycle+1;
  if(checking && dut.axis_host_send[0].tvalid && dut.axis_host_send[0].tready)begin
   if(dut.axis_host_send[0].tdata!==packet(forwarded) || dut.axis_host_send[0].tkeep!==64'hffffffffffffffff ||
      dut.axis_host_send[0].tlast!==(forwarded+1==total) || dut.axis_host_send[0].tid!==6'd3)$fatal(1,"forwarding mismatch");
   forwarded=forwarded+1;
  end
  if(dut.aresetn && dut.sq_rd.valid && dut.sq_rd.ready)begin
   if(variant!=11 || dma_delay>=0 || dut.sq_rd.data.dest!=1 || dut.sq_rd.data.pid!=3 || dut.sq_rd.data.len!=64 ||
      !dut.sq_rd.data.last || dut.sq_rd.data.opcode!=lynxTypes::LOCAL_READ || dut.sq_rd.data.strm!=lynxTypes::STRM_HOST)$fatal(1,"bad or overlapping DMA request");
   requests=requests+1;dma_addr=dut.sq_rd.data.vaddr;dma_delay=response_delay;
  end
 end
 // Alternate completion-before-data and data-before-completion, including stalls.
 always @(negedge dut.aclk)begin
  dut.sq_rd.ready=(cycle%7)!=0;
  dut.axis_host_send[0].tready=(cycle%31)>12;
  if(variant==11)begin
   dut.cq_rd.valid=0;dut.axis_host_recv[1].tvalid=0;
   if(dma_delay>=0)begin
    if(dma_delay==(requests%2?4:1))begin
     dut.cq_rd.valid=1;dut.cq_rd.data='0;dut.cq_rd.data.dest=1;dut.cq_rd.data.pid=3;
    end
    if(dma_delay==(requests%2?1:4))begin
     dut.axis_host_recv[1].tvalid=1;dut.axis_host_recv[1].tdata=0;
     dut.axis_host_recv[1].tkeep='1;dut.axis_host_recv[1].tlast=1;dut.axis_host_recv[1].tid=3;
     if(dma_addr==64'h1000)begin
      if(requests%4>=2) dut.axis_host_recv[1].tdata[63:0]={~32'(frame+100),32'(frame+100)};
      else dut.axis_host_recv[1].tdata[63:0]={~32'd99,32'd99};
     end else if(dma_addr==64'h1040)begin
      dut.axis_host_recv[1].tdata[127:0]={64'(frame+100+(corrupt?1:0)),32'h43565234,32'hbf800000};
     end else $fatal(1,"bad mailbox address");
    end
    dma_delay=dma_delay-1;
   end
  end
 end
 task wr(input integer index,input logic [63:0] data);
  @(negedge dut.aclk);dut.axi_ctrl.awaddr=index*8;dut.axi_ctrl.awvalid=1;
  do @(posedge dut.aclk);while(!dut.axi_ctrl.awready);
  @(negedge dut.aclk);dut.axi_ctrl.awvalid=0;
  repeat(2)@(negedge dut.aclk);
  dut.axi_ctrl.wdata=data;dut.axi_ctrl.wstrb='1;dut.axi_ctrl.wvalid=1;
  do @(posedge dut.aclk);while(!dut.axi_ctrl.wready);
  @(negedge dut.aclk);dut.axi_ctrl.wvalid=0;wait(dut.axi_ctrl.bvalid);@(negedge dut.aclk);
 endtask
 task rd(input integer index,output logic [63:0] data);
  @(negedge dut.aclk);dut.axi_ctrl.araddr=index*8;dut.axi_ctrl.arvalid=1;
  do @(posedge dut.aclk);while(!dut.axi_ctrl.arready);
  @(negedge dut.aclk);dut.axi_ctrl.arvalid=0;wait(dut.axi_ctrl.rvalid);data=dut.axi_ctrl.rdata;
 endtask
 task host_result;
  @(negedge dut.aclk);dut.axis_host_recv[1].tvalid=1;
  dut.axis_host_recv[1].tdata={384'b0,64'(frame+100+(corrupt?1:0)),32'h43565234,32'hbf800000};
  dut.axis_host_recv[1].tkeep='1;dut.axis_host_recv[1].tlast=1;dut.axis_host_recv[1].tid=3;
  do @(posedge dut.aclk);while(!dut.axis_host_recv[1].tready);
  @(negedge dut.aclk);dut.axis_host_recv[1].tvalid=0;
 endtask
 task send_frame;
  for(integer i=0;i<total;i++)begin
   @(negedge dut.aclk);dut.axis_host_recv[0].tvalid=1;dut.axis_host_recv[0].tdata=packet(i);
   dut.axis_host_recv[0].tkeep='1;dut.axis_host_recv[0].tlast=i+1==total;dut.axis_host_recv[0].tid=3;
   do @(posedge dut.aclk);while(!dut.axis_host_recv[0].tready);
   @(negedge dut.aclk);dut.axis_host_recv[0].tvalid=0;
  end
 endtask
 logic [63:0] value;
 initial begin #2000000;$fatal(1,"testbench timeout");end
 initial begin
  dut.axi_ctrl.awvalid=0;dut.axi_ctrl.wvalid=0;dut.axi_ctrl.arvalid=0;dut.axi_ctrl.bready=1;dut.axi_ctrl.rready=1;
  dut.axis_host_recv[0].tvalid=0;dut.axis_host_recv[1].tvalid=0;dut.axis_host_send[1].tready=1;
  dut.cq_rd.valid=0;dut.cq_wr.valid=0;dut.cq_rd.data='0;dut.cq_wr.data='0;dut.sq_wr.ready=1;dut.notify.ready=1;
  repeat(8)@(negedge dut.aclk);dut.aresetn=1;
  repeat(20000)@(negedge dut.aclk);dut.aresetn=0;
  repeat(8)@(negedge dut.aclk);dut.aresetn=1;
  rd(4,value);variant=value[15:0];if(value[63:16]!=48'h434259540004)$fatal(1,"wrong ABI");
  wr(32,'h1000);wr(33,'h1040);wr(34,3);wr(35,5);
  for(frame=0;frame<3;frame++)begin
   n=frame==0?0:frame==1?65:65537;total=1+(n+63)/64;forwarded=0;requests=0;checking=1;
   wr(1,n);wr(2,frame+100);wr(0,1);
   if(variant==10)begin
    host_result();repeat(20)@(negedge dut.aclk);
    rd(0,value);if(value!=1)$fatal(1,"early result completed before input");
   end
   send_frame();
   do rd(0,value);while(value==1);
   if(value!=2)$fatal(1,"completion status %h",value);
   rd(20,value);if(value!=total)$fatal(1,"input count");
   rd(26,value);if(value!=64'hbf800000)$fatal(1,"verdict");
   if(variant==11)begin
    if(forwarded!=total || requests<3)$fatal(1,"forwarding/polling missing");
    rd(16,value);if(value!=0)$fatal(1,"autonomous CQ contaminated raw ACK");
    rd(42,value);if(value!=requests)$fatal(1,"poll count");
   end
   checking=0;repeat(10)@(negedge dut.aclk);
  end
  // Reject a committed payload for another trial.
  corrupt=1;n=0;total=1;requests=0;wr(1,0);wr(2,frame+100);wr(0,1);send_frame();
  if(variant==10)host_result();
  do rd(0,value);while(value==1);
  if(value!=6)$fatal(1,"wrong trial accepted");
  corrupt=0;frame=frame+1;
  // Timeout with outstanding P2P request: reject rearm and drain before idle.
  response_delay=200;requests=0;wr(36,50);wr(2,frame+100);wr(0,1);send_frame();
  do rd(0,value);while(value==1);
  if(value!=6)$fatal(1,"timeout not reported");
  if(variant==11)begin
   rd(37,value);if(value!=1)$fatal(1,"outstanding read not retained");
   wr(0,1);rd(0,value);if(value!=6)$fatal(1,"rearm during drain accepted");
   repeat(250)@(negedge dut.aclk);rd(37,value);if(value!=0)$fatal(1,"read did not drain");
  end
  $display("PASS GPU variant %0d: bytes/stalls, early verdict, stale polls, CQ ordering, invalid trial, timeout/drain, idle-reset, consecutive frames",variant);$finish;
 end
endmodule
