`timescale 1ns/1ps
// Actual synthesized HLS cores and the maintained FIFO, no behavioral IP stubs.
module direct_pipe_tb #(parameter integer STARTUP_IDLE=0, parameter bit ALWAYS_READY=0,
                        parameter integer INTERFRAME_IDLE=20);
reg ap_clk=0;always #2 ap_clk=~ap_clk;
reg ap_rst_n=0;
reg [511:0] data_in_TDATA=0;
reg [63:0] data_in_TKEEP=0,data_in_TSTRB=0;
reg data_in_TLAST=0,data_in_TVALID=0,data_out_TREADY=0;
wire data_in_TREADY,data_out_TVALID,data_out_TLAST;
wire [511:0] data_out_TDATA;wire [63:0] data_out_TKEEP,data_out_TSTRB;
wire [15:0] produced_pixel,consumed_pixel;
wire produced_valid,produced_ready,consumed_valid,consumed_ready;
wire [5:0] occupancy;
wire busy;wire [63:0] trial_id;
reg [63:0] awaddr=0,wdata=0,araddr=0;
reg awvalid=0,wvalid=0,arvalid=0;
wire awready,wready,bvalid,arready,rvalid;wire[1:0] bresp,rresp;wire[63:0] rdata;
direct_control #(.VARIANT(7)) ctrl(
    .clk(ap_clk),.rst_n(ap_rst_n),.awaddr(awaddr),.araddr(araddr),
    .awvalid(awvalid),.wvalid(wvalid),.bready(1'b1),.arvalid(arvalid),.rready(1'b1),
    .wdata(wdata),.wstrb(8'hff),.awready(awready),.wready(wready),.bvalid(bvalid),
    .arready(arready),.rvalid(rvalid),.bresp(bresp),.rresp(rresp),.rdata(rdata),
    .in_valid(data_in_TVALID && busy),.in_ready(data_in_TREADY),.in_last(data_in_TLAST),
    .in_data(data_in_TDATA),.in_keep(data_in_TKEEP),.out_valid(1'b0),.out_ready(1'b0),
    .pp_valid(produced_valid),.pp_ready(produced_ready),.cnn_valid(consumed_valid),.cnn_ready(consumed_ready),
    .fifo_occupancy(occupancy),.read_complete(1'b0),.write_complete(1'b0),
    .result_valid(data_out_TVALID),.result_bits(data_out_TDATA[31:0]),
    .result_trial(trial_id),.result_record_valid(1'b1),.busy(busy),.trial_id(trial_id));
task csr_write(input integer index,input reg[63:0] value);
    awaddr=64'(index*8);wdata=value;awvalid=1;wvalid=1;
    do @(posedge ap_clk);while(!(awready && wready));
    @(negedge ap_clk);awvalid=0;wvalid=0;
    wait(bvalid);@(negedge ap_clk);@(negedge ap_clk);
endtask
task csr_check(input integer index,input reg[63:0] expected);
    araddr=64'(index*8);arvalid=1;
    do @(posedge ap_clk);while(!arready);
    @(negedge ap_clk);arvalid=0;
    wait(rvalid);
    if(rdata!==expected)$fatal(1,"CSR %0d actual=%h expected=%h",index,rdata,expected);
    @(negedge ap_clk);@(negedge ap_clk);
endtask
preprocess_wrapper pp(.ap_clk(ap_clk),.ap_rst_n(ap_rst_n),
    .data_in_TDATA(data_in_TDATA),.data_in_TKEEP(data_in_TKEEP),.data_in_TSTRB(data_in_TSTRB),
    .data_in_TLAST(data_in_TLAST),.data_in_TVALID(data_in_TVALID && busy),.data_in_TREADY(data_in_TREADY),
    .pixels_TDATA(produced_pixel),.pixels_TVALID(produced_valid),.pixels_TREADY(produced_ready));
elastic_fifo #(.WIDTH(16),.DEPTH(32)) fifo(.clk(ap_clk),.rst_n(ap_rst_n),
    .in_data(produced_pixel),.in_valid(produced_valid),.in_ready(produced_ready),
    .out_data(consumed_pixel),.out_valid(consumed_valid),.out_ready(consumed_ready),.occupancy(occupancy));
cnn_wrapper cnn(.ap_clk(ap_clk),.ap_rst_n(ap_rst_n),
    .pixels_TDATA(consumed_pixel),.pixels_TVALID(consumed_valid),.pixels_TREADY(consumed_ready),
    .data_out_TDATA(data_out_TDATA),.data_out_TKEEP(data_out_TKEEP),.data_out_TSTRB(data_out_TSTRB),
    .data_out_TLAST(data_out_TLAST),.data_out_TVALID(data_out_TVALID),.data_out_TREADY(data_out_TREADY));
integer cycle=0,produced=0,consumed=0,first_consume=-1,last_payload=-1,results=0,frame=0;
integer fd,rc,n,expected_n,outfile,progress_file,frame_start;
reg[31:0] expected_bits;reg active=0;
longint unsigned target;integer raw_byte,expected_token;
function automatic integer sample(input integer index,input integer length);
    longint unsigned pos;integer b;
    pos=length>65536?(64'(index)*(64'(length)-1))/65535:64'(index);
    b=pos<64'(length)?((pos*131+pos/11+17)&255):0;
    return ((255-b)*1024)/255;
endfunction
always @(posedge ap_clk)begin
    cycle<=cycle+1;
    if(ap_rst_n && !active && data_out_TVALID && data_out_TREADY)
        $fatal(1,"unsolicited result while idle cycle=%0d",cycle);
    if(ap_rst_n && active)begin
        if(cycle-frame_start>1000000)$fatal(1,"frame stalled frame=%0d bytes=%0d produced=%0d consumed=%0d",frame,n,produced,consumed);
        if((cycle-frame_start)%100000==0)begin
            $fdisplay(progress_file,"%0d,%0d,%0d,%0d,%0d",frame,n,cycle-frame_start,produced,consumed);
            $fflush(progress_file);
        end
        if(produced_valid && produced_ready)begin
            if(produced_pixel!==16'(sample(produced,n)))$fatal(1,"produced pixel mismatch frame=%0d index=%0d",frame,produced);
            produced=produced+1;
        end
        if(consumed_valid && consumed_ready)begin
            if(consumed==0)first_consume=cycle;
            if(consumed_pixel!==16'(sample(consumed,n)))$fatal(1,"CNN pixel mismatch frame=%0d index=%0d",frame,consumed);
            consumed=consumed+1;
        end
        if(data_out_TVALID && data_out_TREADY)begin
            if(data_out_TDATA[31:0]!==expected_bits)$fatal(1,"logit mismatch frame=%0d actual=%h expected=%h",frame,data_out_TDATA[31:0],expected_bits);
            if(produced!=65536 || consumed!=65536)$fatal(1,"pixel counts %0d %0d",produced,consumed);
            if(n>=4194240 && first_consume>=last_payload)$fatal(1,"no streaming overlap");
            $fdisplay(outfile,"%0d,%0d,%0d,%0d,%0d",n,first_consume,last_payload,cycle,cycle-first_consume);
            $fflush(outfile);
            $display("PASS direct frame=%0d bytes=%0d CNN cycles=%0d",frame,n,cycle-first_consume);
            results=results+1;
        end
    end
end
task beat(input reg[511:0] data,input bit last);
    data_in_TDATA=data;data_in_TKEEP=-1;data_in_TSTRB=-1;data_in_TLAST=last;data_in_TVALID=1;
    do @(posedge ap_clk);while(!(data_in_TREADY && busy));
    @(negedge ap_clk);data_in_TVALID=0;
endtask
reg[511:0] payload;
initial begin #400000000;$fatal(1,"direct pipeline deadlock");end
initial begin
    fd=$fopen("direct_expected.txt","r");if(!fd)$fatal(1,"missing pristine reference");
    outfile=$fopen("cycles.csv","w");$fdisplay(outfile,"bytes,first_cnn,last_payload,verdict,cnn_cycles");
    $fflush(outfile);
    progress_file=$fopen("progress.csv","w");$fdisplay(progress_file,"frame,bytes,frame_cycles,produced,consumed");$fflush(progress_file);
    repeat(100)@(negedge ap_clk);ap_rst_n=1;
    if(!ALWAYS_READY)$fatal(1,"Control integration requires the board's always-ready result");
    data_out_TREADY=ALWAYS_READY;
    repeat(STARTUP_IDLE)@(negedge ap_clk);
    while(!$feof(fd))begin
        rc=$fscanf(fd,"%d %h\n",expected_n,expected_bits);if(rc!=2)$fatal(1,"bad reference");
        n=expected_n;produced=0;consumed=0;first_consume=-1;last_payload=-1;frame_start=cycle;active=1;data_out_TREADY=ALWAYS_READY;
        csr_write(1,64'(n));csr_write(2,64'(frame+1));csr_write(0,64'h1);
        repeat(20)@(negedge ap_clk);
        beat(512'(n),n==0);
        for(integer i=0;i<n;i+=64)begin
            payload=0;
            for(integer b=0;b<64 && i+b<n;b++)payload[b*8+:8]=8'((i+b)*131+(i+b)/11+17);
            if((i/64)%113==0)repeat(3)@(negedge ap_clk);
            beat(payload,i+64>=n);last_payload=cycle-1;
        end
        if(!ALWAYS_READY)begin
            wait(data_out_TVALID);
            repeat(7)begin @(negedge ap_clk);if(!data_out_TVALID || data_out_TDATA[31:0]!==expected_bits)$fatal(1,"unstable blocked result");end
            data_out_TREADY=1;
        end
        wait(results==frame+1);
        @(negedge ap_clk);data_out_TREADY=ALWAYS_READY;active=0;
        csr_check(0,64'h2);
        csr_check(2,64'(frame+1));
        csr_check(26,{31'b0,(!expected_bits[31] || expected_bits[30:0]==0),expected_bits});
        csr_check(27,64'd65536);csr_check(28,64'd65536);
        repeat(INTERFRAME_IDLE)@(negedge ap_clk);frame=frame+1;
    end
    $fclose(outfile);$fclose(progress_file);$display("PASS direct synthesized RTL parity: frames=%0d startup_idle=%0d always_ready=%0d",frame,STARTUP_IDLE,ALWAYS_READY);$finish;
end
endmodule
