`timescale 1ns/1ps
// One outstanding 64-byte read. Receive both data and CQ before reissuing.
// Cancel drains the accepted request; software must wait for active=0 to unmap.
module gpu_poll(
 input logic clk,rst_n,busy,input_done,
 input logic [63:0] tick,ready_addr,payload_addr,trial,
 input logic [31:0] gap_cycles,
 output logic req_valid,input logic req_ready,output logic [63:0] req_addr,
 input logic rsp_valid,output logic rsp_ready,input logic [511:0] rsp_data,
 input logic rsp_wellformed,input logic ack,
 output logic active,fatal,result_valid,output logic [31:0] result_bits,
 output logic [63:0] result_trial,output logic [63:0] stats[9]
);
 typedef enum logic [3:0] {IDLE,INPUT_WAIT,READY_REQ,READY_WAIT,GAP,PAYLOAD_REQ,PAYLOAD_WAIT,FINISHED} state_t;
 state_t state;
 logic data_seen,ack_seen,response_ok;
 logic [511:0] response;
 logic [31:0] gap_left;
 wire waiting=state==READY_WAIT || state==PAYLOAD_WAIT;
 wire received=data_seen || (rsp_valid && rsp_ready);
 wire completed=ack_seen || ack;
 wire [511:0] current_data=data_seen?response:rsp_data;
 wire current_ok=data_seen?response_ok:rsp_wellformed;
 assign req_valid=busy && (state==READY_REQ || state==PAYLOAD_REQ);
 assign req_addr=state==PAYLOAD_REQ?payload_addr:ready_addr;
 assign rsp_ready=waiting && !data_seen;
 assign active=state!=IDLE && state!=FINISHED;
 assign stats[8]={60'b0,state};
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;data_seen<=0;ack_seen<=0;response<=0;response_ok<=0;gap_left<=0;
   fatal<=0;result_valid<=0;result_bits<=0;result_trial<=0;
   for(int i=0;i<8;i++)stats[i]<=0;
  end else begin
   fatal<=0;result_valid<=0;
   if(req_valid && !req_ready)stats[6]<=stats[6]+1;
   if(waiting)begin
    if(rsp_valid && rsp_ready)begin data_seen<=1;response<=rsp_data;response_ok<=rsp_wellformed;end
    if(ack)ack_seen<=1;
   end
   if(!busy)begin
    if(!waiting || (received && completed))state<=IDLE;
   end else case(state)
    IDLE:begin
     state<=INPUT_WAIT;
     for(int i=0;i<8;i++)stats[i]<=0;
    end
    INPUT_WAIT:if(input_done)state<=READY_REQ;
    READY_REQ,PAYLOAD_REQ:if(req_ready)begin
     if(stats[4]==0)stats[0]<=tick;
     stats[4]<=stats[4]+1;stats[5]<=stats[5]+64;
     data_seen<=0;ack_seen<=0;
     state<=state==READY_REQ?READY_WAIT:PAYLOAD_WAIT;
    end
    READY_WAIT:if(received && completed)begin
     if(!current_ok)begin fatal<=1;stats[7]<=1;state<=FINISHED;end
     else if(current_data[31:0]==trial[31:0] && current_data[63:32]==~trial[31:0])begin
      stats[2]<=tick;state<=PAYLOAD_REQ;
     end else begin stats[1]<=tick;gap_left<=gap_cycles;state<=GAP;end
    end
    GAP:if(gap_left==0)state<=READY_REQ;else gap_left<=gap_left-1;
    PAYLOAD_WAIT:if(received && completed)begin
     stats[3]<=tick;state<=FINISHED;
     if(!current_ok || current_data[63:32]!=32'h43565234 || current_data[127:64]!=trial || current_data[30:23]==8'hff)begin
      fatal<=1;stats[7]<=2;
     end else begin result_valid<=1;result_bits<=current_data[31:0];result_trial<=current_data[127:64];end
    end
    FINISHED:begin end
    default:state<=IDLE;
   endcase
  end
 end
endmodule
