`timescale 1ns/1ps
// ABI v3. Absolute 64-bit aclk ticks; one armed frame at a time.
// VARIANT: 7=direct checker, 8=sink, 9=GPU pass-through.
module direct_control #(parameter ADDR_BITS=64, DATA_BITS=64, VARIANT=7, FIFO_COUNT_BITS=6)(
    input logic clk,rst_n,
    input logic [ADDR_BITS-1:0] awaddr,araddr,
    input logic awvalid,wvalid,bready,arvalid,rready,
    input logic [DATA_BITS-1:0] wdata,input logic [DATA_BITS/8-1:0] wstrb,
    output logic awready,wready,bvalid,arready,rvalid,
    output logic [1:0] bresp,rresp,output logic [DATA_BITS-1:0] rdata,
    input logic in_valid,in_ready,in_last,input logic [511:0] in_data,
    input logic [63:0] in_keep,
    input logic out_valid,out_ready,
    input logic pp_valid,pp_ready,cnn_valid,cnn_ready,
    input logic [FIFO_COUNT_BITS-1:0] fifo_occupancy,
    input logic read_complete,write_complete,
    input logic result_valid,input logic [31:0] result_bits,
    input logic [63:0] result_trial,input logic result_record_valid,
    output logic busy,output logic [63:0] trial_id
);
    logic have_aw,have_w,done,error_flag;
    logic [ADDR_BITS-1:0] saved_aw;
    logic [DATA_BITS-1:0] saved_w;
    logic [DATA_BITS/8-1:0] saved_strb;
    logic [63:0] tick,origin,raw_bytes,events;
    logic [63:0] stamp[12];
    logic [63:0] in_beats,out_beats,pp_count,cnn_count;
    logic [63:0] starve,blocked_input,blocked_pixels,starved_cnn,max_fifo;
    logic [31:0] score;
    logic verdict;
    wire commit=have_aw && have_w && !bvalid;
    wire go=commit && saved_aw[11:3]==0 && saved_strb[0] && saved_w[0];
    wire rx=in_valid && in_ready && busy;
    wire tx=out_valid && out_ready && busy;
    wire pp=pp_valid && pp_ready && busy;
    wire cnn=cnn_valid && cnn_ready && busy;
    wire [63:0] expected_beats=1+((raw_bytes+63)>>6);
    wire input_finished=in_beats==expected_beats || (rx && in_beats+1==expected_beats);
    assign awready=!have_aw && !bvalid;
    assign wready=!have_w && !bvalid;
    assign arready=!rvalid;
    assign bresp=0;assign rresp=0;
    function automatic [63:0] read_reg(input logic [8:0] index);
        case(index)
            0:read_reg={61'b0,error_flag,done,busy};
            1:read_reg=raw_bytes;
            2:read_reg=trial_id;
            4:read_reg=64'h4342595400030000|64'(VARIANT);
            5:read_reg=tick;
            6:read_reg=origin;
            7:read_reg=events;
            8,9,10,11,12,13,14,15,16,17,18,19:read_reg=stamp[index-8];
            20:read_reg=in_beats;
            21:read_reg=out_beats;
            22:read_reg=starve;
            23:read_reg=blocked_input;
            24:read_reg=blocked_pixels;
            25:read_reg=starved_cnn;
            26:read_reg={31'b0,verdict,score};
            27:read_reg=pp_count;
            28:read_reg=cnn_count;
            29:read_reg=max_fifo;
            default:read_reg=0;
        endcase
    endfunction
    always_ff @(posedge clk) begin
        if(!rst_n) begin
            have_aw<=0;have_w<=0;bvalid<=0;rvalid<=0;rdata<=0;
            saved_aw<=0;saved_w<=0;saved_strb<=0;
            busy<=0;done<=0;error_flag<=0;tick<=0;origin<=0;raw_bytes<=0;trial_id<=0;
            events<=0;in_beats<=0;out_beats<=0;pp_count<=0;cnn_count<=0;
            starve<=0;blocked_input<=0;blocked_pixels<=0;starved_cnn<=0;max_fifo<=0;score<=0;verdict<=0;
            for(int i=0;i<12;i++)stamp[i]<=0;
        end else begin
            tick<=tick+1;
            if(awready && awvalid)begin saved_aw<=awaddr;have_aw<=1;end
            if(wready && wvalid)begin saved_w<=wdata;saved_strb<=wstrb;have_w<=1;end
            if(bvalid && bready)bvalid<=0;
            if(commit)begin
                have_aw<=0;have_w<=0;bvalid<=1;
                if(!busy)for(int b=0;b<8;b++)if(saved_strb[b])begin
                    case(saved_aw[11:3])
                        1:raw_bytes[8*b+:8]<=saved_w[8*b+:8];
                        2:trial_id[8*b+:8]<=saved_w[8*b+:8];
                        default:begin end
                    endcase
                end
            end
            if(rvalid && rready)rvalid<=0;
            if(arvalid && arready)begin rvalid<=1;rdata<=DATA_BITS'(read_reg(araddr[11:3]));end
            if(go)begin
                if(busy || raw_bytes>134217664)error_flag<=1;
                else begin
                    busy<=1;done<=0;error_flag<=0;origin<=tick;events<=0;
                    in_beats<=0;out_beats<=0;pp_count<=0;cnn_count<=0;
                    starve<=0;blocked_input<=0;blocked_pixels<=0;starved_cnn<=0;max_fifo<=0;score<=0;verdict<=0;
                    for(int i=0;i<12;i++)stamp[i]<=0;
                end
            end
            if(busy)begin
                if(!input_finished)begin
                    if(in_ready && !in_valid)starve<=starve+1;
                    if(in_valid && !in_ready)blocked_input<=blocked_input+1;
                end
                if(pp_valid && !pp_ready)blocked_pixels<=blocked_pixels+1;
                if(cnn_ready && !cnn_valid && cnn_count<65536)starved_cnn<=starved_cnn+1;
                if(fifo_occupancy>max_fifo)max_fifo<=fifo_occupancy;
                if(rx)begin
                    in_beats<=in_beats+1;
                    if(in_beats==0 && in_data[63:0]!=raw_bytes)error_flag<=1;
                    if(in_keep!=64'hffffffffffffffff)error_flag<=1;
                    if(in_last!=(in_beats+1==expected_beats))error_flag<=1;
                    if(in_beats>=expected_beats)error_flag<=1;
                    if(in_beats==1)begin stamp[0]<=tick;events[0]<=1;end
                    if(in_beats>0)begin stamp[1]<=tick;events[1]<=1;end
                    if(VARIANT==8 && in_beats+1==expected_beats)begin
                        stamp[7]<=tick;events[7]<=1;done<=1;busy<=0;
                    end
                end
                if(tx)begin
                    if(out_beats==0)begin stamp[10]<=tick;events[10]<=1;end
                    stamp[11]<=tick;events[11]<=1;out_beats<=out_beats+1;
                end
                if(pp)begin
                    if(pp_count==0)begin stamp[2]<=tick;events[2]<=1;end
                    if(pp_count==65535)begin stamp[3]<=tick;events[3]<=1;end
                    pp_count<=pp_count+1;
                    if(pp_count>=65536)error_flag<=1;
                end
                if(cnn)begin
                    if(cnn_count==0)begin stamp[4]<=tick;events[4]<=1;end
                    if(cnn_count==65535)begin stamp[5]<=tick;events[5]<=1;end
                    cnn_count<=cnn_count+1;
                    if(cnn_count>=65536)error_flag<=1;
                end
                if(result_valid)begin
                    if(VARIANT==9 && (!result_record_valid || result_trial!=trial_id))error_flag<=1;
                    else begin
                        stamp[6]<=tick;events[6]<=1;
                        if(!input_finished || (VARIANT==7 && cnn_count!=65536) ||
                           (VARIANT==9 && out_beats!=expected_beats))error_flag<=1;
                        else begin
                            score<=result_bits;
                            // Production decision: logit >= 0, including signed zero.
                            verdict<=!result_bits[31] || result_bits[30:0]==0;
                            if(result_bits[30:23]==8'hff)error_flag<=1;
                            stamp[7]<=tick;events[7]<=1;done<=1;busy<=0;
                        end
                    end
                end
            end
            // DMA acknowledgments can trail the verdict; retain them until rearm.
            if(!go && origin!=0)begin
                if(read_complete && !events[8])begin stamp[8]<=tick;events[8]<=1;end
                if(write_complete && !events[9])begin stamp[9]<=tick;events[9]<=1;end
            end
        end
    end
endmodule
