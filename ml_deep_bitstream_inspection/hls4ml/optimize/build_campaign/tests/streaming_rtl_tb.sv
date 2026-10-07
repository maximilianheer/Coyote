`timescale 1ns/1ps
// Real synthesized HLS RTL, not the elaboration stub. Deterministic payloads
// match csim.cpp. Exercise consecutive frames and both AXIS stall directions.
module streaming_rtl_tb;
reg ap_clk=0; always #2 ap_clk=~ap_clk;
reg ap_rst_n=0;
reg [511:0] data_in_TDATA=0;
reg [63:0] data_in_TKEEP=0, data_in_TSTRB=0;
reg data_in_TLAST=0, data_in_TVALID=0, data_out_TREADY=0;
wire data_in_TREADY, data_out_TVALID, data_out_TLAST;
wire [511:0] data_out_TDATA;
wire [63:0] data_out_TKEEP, data_out_TSTRB;
wire [31:0] pp_start, pp_end, cnn_start, logit, produced_tokens;
model_wrapper dut(.*);
integer cycle=0, consumed=0, first_consume=-1, last_payload=-1;
integer results=0, frame=0, fd, rc;
integer n, expected_n;
reg [31:0] expected_bits;
reg active=0;
reg [3:0] events_before;
reg [3:0] previous_events=0;
reg header_seen=0;
integer event_count[4]='{0,0,0,0};
longint unsigned target;
integer raw_byte, expected_token;
always @(posedge ap_clk) begin
 cycle <= cycle+1;
 if(ap_rst_n) begin
  if(active && data_in_TVALID && data_in_TREADY) header_seen=1;
  for(integer e=0;e<4;e++) begin
   if(({logit[0],cnn_start[0],pp_end[0],pp_start[0]} ^ previous_events) & (4'b1 << e)) begin
    if(!active || !header_seen) $fatal(1,"stage event without accepted frame: %0d",e);
    event_count[e]=event_count[e]+1;
    if(event_count[e]!=1) $fatal(1,"duplicate stage event frame=%0d event=%0d",frame,e);
   end
  end
  previous_events={logit[0],cnn_start[0],pp_end[0],pp_start[0]};
 end
 if(ap_rst_n && active && dut.bitstream_input_U.if_read && dut.bitstream_input_U.if_empty_n) begin
  if(consumed==0) first_consume=cycle;
  target=n>65536 ? (64'(consumed)*(64'(n)-1))/65535 : 64'(consumed);
  raw_byte=target<64'(n) ? ((target*131+target/11+17)&255) : 0;
  expected_token=((255-raw_byte)*1024)/255;
  if(dut.bitstream_input_U.if_dout !== 16'(expected_token)) $fatal(1,"token parity frame=%0d token=%0d",frame,consumed);
  consumed=consumed+1;
 end
 if(ap_rst_n && active && data_out_TVALID && data_out_TREADY) begin
  if(data_out_TDATA[31:0] !== expected_bits) $fatal(1,"logit mismatch frame=%0d actual=%h expected=%h",frame,data_out_TDATA[31:0],expected_bits);
  if({logit[0],cnn_start[0],pp_end[0],pp_start[0]} !== ~events_before) $fatal(1,"stage events before=%b after=%b",events_before,{logit[0],cnn_start[0],pp_end[0],pp_start[0]});
  if(consumed!=65536 || produced_tokens!=65536) $fatal(1,"token count %0d %0d",consumed,produced_tokens);
  for(integer e=0;e<4;e++) if(event_count[e]!=1) $fatal(1,"missing stage event %0d",e);
  if(n>=4194240 && !(first_consume<last_payload)) $fatal(1,"CNN consumption did not overlap reception");
  $display("PASS RTL frame=%0d bytes=%0d first_pixel=%0d last_payload=%0d decision=%0d tokens=%0d",frame,n,first_consume,last_payload,cycle,consumed);
  results=results+1;
 end
end
task beat(input reg [511:0] data,input reg[63:0] keep,input bit last);
 data_in_TDATA=data;data_in_TKEEP=keep;data_in_TSTRB=keep;data_in_TLAST=last;data_in_TVALID=1;
 do @(posedge ap_clk); while(!data_in_TREADY);
 @(negedge ap_clk);data_in_TVALID=0;
endtask
reg [511:0] payload;
reg [63:0] keep;
initial begin
 #400000000;$fatal(1,"deadlock timeout");
end
initial begin
 fd=$fopen("rtl_expected.txt","r");if(!fd)$fatal(1,"missing C-simulation reference");
 repeat(10) @(negedge ap_clk);ap_rst_n=1;
 while(!$feof(fd)) begin
  rc=$fscanf(fd,"%d %h\n",expected_n,expected_bits);
  if(rc!=2) $fatal(1,"bad reference");
  events_before={logit[0],cnn_start[0],pp_end[0],pp_start[0]};
  $display("BEGIN frame=%0d events=%b",frame,events_before);
  n=expected_n;consumed=0;first_consume=-1;last_payload=-1;active=1;data_out_TREADY=0;header_seen=0;
  for(integer e=0;e<4;e++) event_count[e]=0;
  repeat(20) @(negedge ap_clk); // no speculative events before the header
  beat(512'(n),64'hffffffffffffffff,n==0);
  for(integer i=0;i<n;i+=64) begin
   payload=0;keep=0;
   for(integer b=0;b<64 && i+b<n;b++) begin
    payload[b*8+:8]=8'((i+b)*131+(i+b)/11+17);keep[b]=1;
   end
   if((i/64)%113==0) repeat(3) @(negedge ap_clk);
   beat(payload,keep,i+64>=n); last_payload=cycle-1;
  end
  // Stall the result for seven cycles once valid and require stable data.
  wait(data_out_TVALID);
  repeat(7) begin @(negedge ap_clk); if(!data_out_TVALID || data_out_TDATA[31:0]!==expected_bits) $fatal(1,"output stall"); end
  data_out_TREADY=1;wait(results==frame+1);
  @(negedge ap_clk);data_out_TREADY=0;active=0;
  repeat(20) @(negedge ap_clk);frame=frame+1;
 end
 $display("PASS synthesized streaming RTL consecutive frames, stalls, parity and early pixel consumption");$finish;
end
endmodule
