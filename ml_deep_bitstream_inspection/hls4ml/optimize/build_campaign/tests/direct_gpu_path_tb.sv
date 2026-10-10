`timescale 1ns/1ps
// Exercise the maintained GPU top with actual Coyote interfaces and control.
// Only the debug ILA is a stub; this variant contains no HLS model cores.
module direct_gpu_path_tb;
top_elaboration dut();
always #2 dut.aclk=~dut.aclk;
integer cycle=0,frame=0,n=0,forwarded=0,total=0;
logic checking=0;
localparam TID_BITS=lynxTypes::PID_BITS;
function automatic [511:0] packet(input integer index);
    reg [511:0] value;
    for(integer b=0;b<64;b++)value[b*8+:8]=8'(frame*19+index*131+b*7);
    if(index==0)value[63:0]=64'(n);
    return value;
endfunction
always @(posedge dut.aclk)begin
    cycle=cycle+1;
    if(dut.aresetn && checking && dut.axis_host_send[0].tvalid && dut.axis_host_send[0].tready)begin
        if(dut.axis_host_send[0].tdata!==packet(forwarded) ||
           dut.axis_host_send[0].tkeep!==64'hffffffffffffffff ||
           dut.axis_host_send[0].tlast!==(forwarded+1==total) ||
           dut.axis_host_send[0].tid!==TID_BITS'(forwarded+frame+1))
            $fatal(1,"forwarded frame/sideband mismatch frame=%0d beat=%0d",frame,forwarded);
        forwarded=forwarded+1;
    end
end
always @(negedge dut.aclk)dut.axis_host_send[0].tready=(cycle%67)>35;
task wr(input integer index,input logic [63:0] data);
    @(negedge dut.aclk);dut.axi_ctrl.awaddr=index*8;dut.axi_ctrl.awvalid=1;
    do @(posedge dut.aclk);while(!dut.axi_ctrl.awready);
    @(negedge dut.aclk);dut.axi_ctrl.awvalid=0;
    repeat(2)@(negedge dut.aclk);
    dut.axi_ctrl.wdata=data;dut.axi_ctrl.wstrb='1;dut.axi_ctrl.wvalid=1;
    do @(posedge dut.aclk);while(!dut.axi_ctrl.wready);
    @(negedge dut.aclk);dut.axi_ctrl.wvalid=0;
    wait(dut.axi_ctrl.bvalid);@(negedge dut.aclk);
endtask
task rd(input integer index,output logic [63:0] data);
    @(negedge dut.aclk);dut.axi_ctrl.araddr=index*8;dut.axi_ctrl.arvalid=1;
    do @(posedge dut.aclk);while(!dut.axi_ctrl.arready);
    @(negedge dut.aclk);dut.axi_ctrl.arvalid=0;
    wait(dut.axi_ctrl.rvalid);data=dut.axi_ctrl.rdata;
endtask
logic [63:0] value;
initial begin #1000000;$fatal(1,"GPU path timeout");end
initial begin
    dut.axi_ctrl.awvalid=0;dut.axi_ctrl.wvalid=0;dut.axi_ctrl.arvalid=0;
    dut.axi_ctrl.bready=1;dut.axi_ctrl.rready=1;
    dut.axis_host_recv[0].tvalid=0;dut.axis_host_recv[1].tvalid=0;
    dut.axis_host_send[1].tready=1;
    dut.cq_rd.valid=0;dut.cq_wr.valid=0;dut.cq_rd.data='0;dut.cq_wr.data='0;
    dut.sq_rd.ready=1;dut.sq_wr.ready=1;dut.notify.ready=1;
    repeat(8)@(negedge dut.aclk);dut.aresetn=1;
    rd(4,value);if(value!=64'h4342595400030009)$fatal(1,"wrong GPU variant");
    for(frame=0;frame<3;frame++)begin
        n=frame==0?0:frame==1?65:65537;total=1+(n+63)/64;
        forwarded=0;checking=1;
        wr(1,n);wr(2,frame+100);wr(0,1);
        for(integer i=0;i<total;i++)begin
            @(negedge dut.aclk);
            dut.axis_host_recv[0].tdata=packet(i);
            dut.axis_host_recv[0].tkeep='1;
            dut.axis_host_recv[0].tlast=(i+1==total);
            dut.axis_host_recv[0].tid=TID_BITS'(i+frame+1);
            dut.axis_host_recv[0].tvalid=1;
            do @(posedge dut.aclk);while(!dut.axis_host_recv[0].tready);
            @(negedge dut.aclk);dut.axis_host_recv[0].tvalid=0;
        end
        wait(forwarded==total);
        @(negedge dut.aclk);dut.cq_rd.valid=1;dut.cq_wr.valid=1;
        @(negedge dut.aclk);dut.cq_rd.valid=0;dut.cq_wr.valid=0;
        dut.axis_host_recv[1].tdata={384'b0,64'(frame+100),32'h43565233,32'hbf800000};
        dut.axis_host_recv[1].tkeep='1;dut.axis_host_recv[1].tlast=1;
        dut.axis_host_recv[1].tid=1;dut.axis_host_recv[1].tvalid=1;
        do @(posedge dut.aclk);while(!dut.axis_host_recv[1].tready);
        @(negedge dut.aclk);dut.axis_host_recv[1].tvalid=0;
        rd(0,value);if(value!=2)$fatal(1,"GPU completion/error %h",value);
        rd(20,value);if(value!=total)$fatal(1,"ingress count");
        rd(21,value);if(value!=total)$fatal(1,"egress count");
        rd(26,value);if(value!=64'hbf800000)$fatal(1,"GPU returned verdict");
        rd(7,value);if(value[11:6]!=6'b111111)$fatal(1,"missing GPU timestamp events");
        if(dut.axis_host_recv[0].tready || dut.axis_host_recv[1].tready)$fatal(1,"unarmed input accepted");
        checking=0;
    end
    $display("PASS GPU path: bytes, keep, last, TID, stalls, FIFO wrap, consecutive frames, returned verdict and timestamps");
    $finish;
end
endmodule
