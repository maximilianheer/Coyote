`timescale 1ns/1ps
// Fixed empty-input diagnostic of the actual routed application netlist.
// All reset replicas have verified identical drivers. Physical skew is excluded.
// The header comparator crosses the shell boundary: equality of zero header and
// zero raw length gives S=2'b11, CO=0. Assert those operands before the handshake.
module routed_userlogic_tb;
reg clk=0; always #2 clk=~clk;
reg rst_n=0, valid=0;
wire ready,busy,busy_rep;
reg [8:0] awaddr=0,araddr=0;
reg [63:0] wdata=0;
reg awvalid=0,wvalid=0,arvalid=0;
wire awready,wready,bvalid,arready,rvalid,exported_arready;
// Physical export aliases axi_ctrl_arready to rvalid_reg_0. The actual
// rdata-register CE is LUT2 INIT=4'h2: arvalid && !rvalid_reg_0.
// Reconstruct the local read-accept condition; external PCIe logic is excluded.
assign arready=!exported_arready;
wire [63:0] rdata;
wire [5:0] raw_low;
design_user_logic_c0_0 dut(
    .aclk_BUFG(clk),.aresetn(rst_n),.p_0_in(rst_n),
    .busy(busy),.busy_reg_rep_n_0_alias(busy_rep),
    .m_axis_tdata(512'b0),.m_axis_tkeep(64'hffffffffffffffff),
    .m_axis_tlast(1'b1),.m_axis_tvalid(valid),.m_axis_tready(ready),
    .data_in_TVALID(valid && busy_rep),.S(2'b11),.CO(1'b0),.Q(raw_low),
    .axi_ctrl_awaddr(awaddr),.axi_ctrl_awvalid(awvalid),.axi_ctrl_awready(awready),
    .axi_ctrl_wdata(wdata),.axi_ctrl_wstrb(8'hff),.axi_ctrl_wvalid(wvalid),
    .axi_ctrl_wready(wready),.axi_ctrl_bready(1'b1),.axi_ctrl_bvalid(bvalid),
    .axi_ctrl_araddr(araddr),.axi_ctrl_arvalid(arvalid),.axi_ctrl_arready(exported_arready),
    .axi_ctrl_rready(1'b1),.axi_ctrl_rvalid(rvalid),.axi_ctrl_rdata(rdata),
    .bpss_rd_cq_valid(1'b0),.bpss_wr_cq_valid(1'b0),
    .\bpss_rd_cq_data[dest] (4'b0),.\bpss_wr_cq_data[dest] (4'b0),
    .sl_iport0(37'b0),.sl_oport0(),.xfer_0(),
    .\peripheral_aresetn[0]_repN_1_alias (rst_n),
    .\peripheral_aresetn[0]_repN_2_alias (rst_n),
    .\peripheral_aresetn[0]_repN_3_alias (rst_n),
    .\peripheral_aresetn[0]_repN_4_alias (rst_n),
    .\peripheral_aresetn[0]_repN_5_alias (rst_n),
    .\peripheral_aresetn[0]_repN_6_alias (rst_n),
    .\peripheral_aresetn[0]_repN_7_alias (rst_n),
    .\peripheral_aresetn[0]_repN_8_alias (rst_n),
    .\peripheral_aresetn[0]_repN_9_alias (rst_n),
    .\peripheral_aresetn[0]_repN_10_alias (rst_n),
    .\peripheral_aresetn[0]_repN_11_alias (rst_n),
    .\peripheral_aresetn[0]_repN_12_alias (rst_n),
    .\peripheral_aresetn[0]_repN_13_alias (rst_n),
    .\peripheral_aresetn[0]_repN_14_alias (rst_n),
    .\peripheral_aresetn[0]_repN_15_alias (rst_n),
    .\peripheral_aresetn[0]_repN_16_alias (rst_n),
    .\peripheral_aresetn[0]_repN_17_alias (rst_n),
    .\peripheral_aresetn[0]_repN_18_alias (rst_n),
    .\peripheral_aresetn[0]_repN_19_alias (rst_n),
    .\peripheral_aresetn[0]_repN_20_alias (rst_n),
    .\peripheral_aresetn[0]_repN_21_alias (rst_n),
    .\peripheral_aresetn[0]_repN_22_alias (rst_n),
    .\peripheral_aresetn[0]_repN_23_alias (rst_n),
    .\peripheral_aresetn[0]_repN_24_alias (rst_n),
    .\peripheral_aresetn[0]_repN_25_alias (rst_n),
    .\peripheral_aresetn[0]_repN_26_alias (rst_n),
    .\peripheral_aresetn[0]_repN_27_alias (rst_n),
    .\peripheral_aresetn[0]_repN_28_alias (rst_n),
    .\peripheral_aresetn[0]_repN_29_alias (rst_n),
    .\peripheral_aresetn[0]_repN_30_alias (rst_n),
    .\peripheral_aresetn[0]_repN_31_alias (rst_n),
    .\peripheral_aresetn[0]_repN_32_alias (rst_n),
    .\peripheral_aresetn[0]_repN_33_alias (rst_n),
    .\peripheral_aresetn[0]_repN_34_alias (rst_n),
    .\peripheral_aresetn[0]_repN_35_alias (rst_n),
    .\peripheral_aresetn[0]_repN_36_alias (rst_n),
    .\peripheral_aresetn[0]_repN_37_alias (rst_n),
    .\peripheral_aresetn[0]_repN_38_alias (rst_n),
    .\peripheral_aresetn[0]_repN_39_alias (rst_n),
    .\peripheral_aresetn[0]_repN_40_alias (rst_n),
    .\peripheral_aresetn[0]_repN_41_alias (rst_n),
    .\peripheral_aresetn[0]_repN_42_alias (rst_n),
    .\peripheral_aresetn[0]_repN_43_alias (rst_n),
    .\peripheral_aresetn[0]_repN_44_alias (rst_n),
    .\peripheral_aresetn[0]_repN_45_alias (rst_n),
    .\peripheral_aresetn[0]_repN_46_alias (rst_n),
    .\peripheral_aresetn[0]_repN_47_alias (rst_n),
    .\peripheral_aresetn[0]_repN_48_alias (rst_n),
    .\peripheral_aresetn[0]_repN_49_alias (rst_n),
    .\peripheral_aresetn[0]_repN_50_alias (rst_n),
    .\peripheral_aresetn[0]_repN_51_alias (rst_n),
    .\peripheral_aresetn[0]_repN_52_alias (rst_n),
    .\peripheral_aresetn[0]_repN_53_alias (rst_n),
    .\peripheral_aresetn[0]_repN_54_alias (rst_n),
    .\peripheral_aresetn[0]_repN_55_alias (rst_n),
    .\peripheral_aresetn[0]_repN_56_alias (rst_n),
    .\peripheral_aresetn[0]_repN_57_alias (rst_n),
    .\peripheral_aresetn[0]_repN_58_alias (rst_n),
    .\peripheral_aresetn[0]_repN_59_alias (rst_n),
    .\peripheral_aresetn[0]_repN_60_alias (rst_n),
    .\peripheral_aresetn[0]_repN_61_alias (rst_n),
    .\peripheral_aresetn[0]_repN_62_alias (rst_n),
    .\peripheral_aresetn[0]_repN_63_alias (rst_n),
    .\peripheral_aresetn[0]_repN_64_alias (rst_n),
    .\peripheral_aresetn[0]_repN_65_alias (rst_n),
    .\peripheral_aresetn[0]_repN_66_alias (rst_n),
    .\peripheral_aresetn[0]_repN_67_alias (rst_n),
    .\peripheral_aresetn[0]_repN_68_alias (rst_n),
    .\peripheral_aresetn[0]_repN_69_alias (rst_n),
    .\peripheral_aresetn[0]_repN_70_alias (rst_n),
    .\peripheral_aresetn[0]_repN_71_alias (rst_n),
    .\peripheral_aresetn[0]_repN_72_alias (rst_n),
    .\peripheral_aresetn[0]_repN_73_alias (rst_n),
    .\peripheral_aresetn[0]_repN_74_alias (rst_n),
    .\peripheral_aresetn[0]_repN_75_alias (rst_n),
    .\peripheral_aresetn[0]_repN_76_alias (rst_n),
    .\peripheral_aresetn[0]_repN_77_alias (rst_n),
    .\peripheral_aresetn[0]_repN_78_alias (rst_n),
    .\peripheral_aresetn[0]_repN_79_alias (rst_n),
    .\peripheral_aresetn[0]_repN_80_alias (rst_n),
    .\peripheral_aresetn[0]_repN_81_alias (rst_n),
    .\peripheral_aresetn[0]_repN_82_alias (rst_n),
    .\peripheral_aresetn[0]_repN_83_alias (rst_n)
);
task csr_write(input integer index,input reg[63:0] value);
    awaddr=9'(index);wdata=value;awvalid=1;wvalid=1;
    do @(posedge clk);while(!(awready && wready));
    @(negedge clk);awvalid=0;wvalid=0;
    wait(bvalid);repeat(2)@(negedge clk);
endtask
task csr_check(input integer index,input reg[63:0] expected);
    araddr=9'(index);arvalid=1;
    do @(posedge clk);while(!arready);
    @(negedge clk);arvalid=0;
    wait(rvalid);
    if(rdata!==expected)$fatal(1,"CSR %0d actual=%h expected=%h",index,rdata,expected);
    $display("PASS routed CSR index=%0d value=%h",index,rdata);
    repeat(2)@(negedge clk);
endtask
integer cycle=0,produced=0,consumed=0,first_cnn=-1,score_cycle=-1,logfile;
reg active=0,score_seen=0;
// Post-route pp_ready names the full flag (occupancy bit 5), not RTL TREADY.
// Observe the actual RAM write enable and read-pointer clock enable instead.
wire fifo_push=dut.\checker_path.pixel_fifo .p_0_in_10;
wire fifo_pop=dut.\checker_path.pixel_fifo .p_0_in_0[0];
always @(posedge clk)begin
    cycle=cycle+1;
    if(cycle%10000==0)begin
        $fdisplay(logfile,"%0d,%0d,%0d,%0d",cycle,produced,consumed,score_seen);$fflush(logfile);
    end
    if(cycle>200000)$fatal(1,"routed application deadlock");
    if(score_seen && cycle>score_cycle+256)$fatal(1,"routed CSR handshake timeout");
    if(rst_n && active)begin
        if(exported_arready!==rvalid)$fatal(1,"exported ARREADY alias changed");
        if(fifo_push)begin
            if(dut.pp_pixel!==16'd1024)$fatal(1,"routed PP pixel %0d actual=%h",produced,dut.pp_pixel);
            produced=produced+1;
        end
        if(fifo_pop)begin
            if(first_cnn<0)first_cnn=cycle;
            if(dut.cnn_pixel!==16'd1024)$fatal(1,"routed FIFO pixel %0d actual=%h",consumed,dut.cnn_pixel);
            consumed=consumed+1;
        end
        if(consumed>produced || produced-consumed>32)$fatal(1,"FIFO accounting produced=%0d consumed=%0d",produced,consumed);
        if(dut.result_valid)begin
            if(score_seen)$fatal(1,"duplicate score");
            if(dut.model_result!==32'hbf2f4000)$fatal(1,"routed score actual=%h expected=bf2f4000",dut.model_result);
            if(produced!=65536 || consumed!=65536)$fatal(1,"pixel counts %0d %0d",produced,consumed);
            score_seen=1;score_cycle=cycle;
            $display("PASS routed score pixels=%0d CNN_cycles=%0d",consumed,score_cycle-first_cnn);
        end
    end
end
initial begin
    logfile=$fopen("progress.csv","w");$fdisplay(logfile,"cycle,produced,consumed,score_seen");$fflush(logfile);
    repeat(100)@(negedge clk);rst_n=1;
    repeat(20000)@(negedge clk);
    csr_write(1,0);csr_write(2,1);csr_write(0,1);
    repeat(20)@(negedge clk);
    if({dut.control.raw_bytes,raw_low}!==64'b0)$fatal(1,"fixed header-comparator assumptions violated");
    active=1;valid=1;
    do @(posedge clk);while(!ready);
    @(negedge clk);valid=0;
    wait(score_seen);repeat(4)@(negedge clk);
    csr_check(0,64'h2);csr_check(2,1);csr_check(26,64'h00000000bf2f4000);
    csr_check(27,65536);csr_check(28,65536);
    $fclose(logfile);$display("PASS routed application: empty frame, exact pixels/logit and CSR verdict");$finish;
end
endmodule
