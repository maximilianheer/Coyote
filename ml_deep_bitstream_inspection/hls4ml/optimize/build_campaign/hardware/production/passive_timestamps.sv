`timescale 1ns/1ps
// R_SO_T observer ABI v1. All timestamps use the same free-running counter.
// No output connects to the datapath. AXI-Lite writes return SLVERR.
// One outstanding production request; read registers after result DMA completes.
module passive_timestamps #(
    parameter ADDR_BITS=64, DATA_BITS=64
)(
    input logic clk, rst_n,
    input logic [ADDR_BITS-1:0] awaddr, araddr,
    input logic awvalid, wvalid, bready, arvalid, rready,
    input logic [DATA_BITS-1:0] wdata,
    input logic [DATA_BITS/8-1:0] wstrb,
    output logic awready, wready, bvalid, arready, rvalid,
    output logic [1:0] bresp, rresp,
    output logic [DATA_BITS-1:0] rdata,
    input logic in_valid, in_ready,
    input logic [63:0] in_length,
    input logic pixel_write, pixel_read,
    input logic out_valid, out_ready
);
    logic [63:0] tick, frame_id, raw_bytes, input_beats;
    logic [63:0] stamp[5];
    logic [16:0] pp_count, cnn_count;
    logic [4:0] events;
    logic active, error_flag, have_aw, have_w;
    wire rx = in_valid && in_ready;
    wire first_beat = rx && !active;
    wire [63:0] expected_beats = 1 + ((raw_bytes + 63) >> 6);

    assign awready = !have_aw && !bvalid;
    assign wready = !have_w && !bvalid;
    assign arready = !rvalid;
    assign bresp = 2'b10;
    assign rresp = 2'b00;

    function automatic [63:0] read_reg(input logic [8:0] index);
        case(index)
            0: read_reg = 64'h52534f5400010000; // RSOT, ABI 1
            1: read_reg = tick;
            2: read_reg = frame_id;
            3: read_reg = {61'b0,error_flag,events[4],active};
            4: read_reg = {59'b0,events};
            5,6,7,8,9: read_reg = stamp[index-5];
            10: read_reg = {47'b0,pp_count};
            11: read_reg = {47'b0,cnn_count};
            12: read_reg = raw_bytes;
            13: read_reg = input_beats;
            default: read_reg = 0;
        endcase
    endfunction

    always_ff @(posedge clk) begin
        if(!rst_n) begin
            tick<=0; frame_id<=0; raw_bytes<=0; input_beats<=0;
            pp_count<=0; cnn_count<=0; events<=0; active<=0; error_flag<=0;
            have_aw<=0; have_w<=0; bvalid<=0; rvalid<=0; rdata<=0;
            for(int i=0;i<5;i++) stamp[i]<=0;
        end else begin
            tick<=tick+1;
            // Split AW/W channels are consumed, with no register side effects.
            if(awvalid && awready) have_aw<=1;
            if(wvalid && wready) have_w<=1;
            if(have_aw && have_w && !bvalid) begin
                have_aw<=0; have_w<=0; bvalid<=1;
            end
            if(bvalid && bready) bvalid<=0;
            if(rvalid && rready) rvalid<=0;
            if(arvalid && arready) begin
                rvalid<=1;
                rdata<=DATA_BITS'(read_reg(araddr[11:3]));
            end

            if(first_beat) begin
                // Header is included in T_in, even for zero-length payloads.
                frame_id<=frame_id+1; raw_bytes<=in_length; input_beats<=1;
                pp_count<=0; cnn_count<=0; events<=5'b00001; active<=1;
                error_flag<=in_length>134217664 || pixel_write || pixel_read || out_valid;
                stamp[0]<=tick;
                for(int i=1;i<5;i++) stamp[i]<=0;
            end else if(active) begin
                if(rx) begin
                    input_beats<=input_beats+1;
                    if(input_beats>=expected_beats) error_flag<=1;
                end
                if(pixel_write) begin
                    if(pp_count==0) begin stamp[1]<=tick; events[1]<=1; end
                    if(pp_count==65535) begin stamp[2]<=tick; events[2]<=1; end
                    if(pp_count<65537) pp_count<=pp_count+1;
                    if(pp_count>=65536 || events[4]) error_flag<=1;
                end
                if(pixel_read) begin
                    if(cnn_count==0) begin stamp[3]<=tick; events[3]<=1; end
                    if(cnn_count<65537) cnn_count<=cnn_count+1;
                    if(cnn_count>=65536 || events[4]) error_flag<=1;
                end
                if(out_valid && !events[4]) begin
                    stamp[4]<=tick; events[4]<=1;
                    if(input_beats+64'(rx)!=expected_beats ||
                       pp_count+17'(pixel_write)!=65536 ||
                       cnn_count+17'(pixel_read)!=65536) error_flag<=1;
                end
                // First-valid timestamp stays frozen throughout output stalls.
                // The next request starts after production result DMA completes.
                if(out_valid && out_ready) active<=0;
            end else if(pixel_write || pixel_read || out_valid) begin
                error_flag<=1;
            end
        end
    end
endmodule
