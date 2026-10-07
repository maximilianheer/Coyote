// Isolate the maintained add-one/handshake logic. Register slices are transparent
// simulation models here; their unchanged Coyote/Xilinx implementation is built normally.
module axisr_reg(AXI4SR.s s_axis, AXI4SR.m m_axis, input logic aclk, aresetn);
always_comb begin
    m_axis.tdata=s_axis.tdata; m_axis.tkeep=s_axis.tkeep;
    m_axis.tlast=s_axis.tlast; m_axis.tvalid=s_axis.tvalid;
    m_axis.tid=s_axis.tid; s_axis.tready=m_axis.tready;
end
endmodule

module hello_tb;
import lynxTypes::*;
logic aclk=0,aresetn=0;
always #5 aclk=~aclk;
AXI4SR axis_in(.*),axis_out(.*);
perf_local dut(.*);
initial begin
    axis_in.tvalid=0;axis_in.tdata=0;axis_in.tkeep=0;axis_in.tlast=0;axis_in.tid=0;
    axis_out.tready=0;
    repeat(3) @(negedge aclk);
    aresetn=1;
    for (int trial=0;trial<64;trial++) begin
        @(negedge aclk);
        axis_in.tvalid=trial[0];axis_out.tready=trial[1];
        axis_in.tlast=trial[2];axis_in.tkeep=64'hffffffffffffffff >> (trial%16);
        axis_in.tid=trial;
        for (int word=0;word<16;word++) axis_in.tdata[word*32+:32]=32'(trial*131+word);
        #1;
        assert(axis_out.tvalid==axis_in.tvalid) else $fatal(1,"TVALID mismatch");
        assert(axis_in.tready==axis_out.tready) else $fatal(1,"backpressure mismatch");
        assert(axis_out.tkeep==axis_in.tkeep && axis_out.tlast==axis_in.tlast && axis_out.tid==axis_in.tid) else $fatal(1,"metadata mismatch");
        for (int word=0;word<16;word++)
            assert(axis_out.tdata[word*32+:32]==axis_in.tdata[word*32+:32]+32'd1) else $fatal(1,"add-one mismatch");
        // Honor AXI stability while a valid beat is blocked.
        if (axis_in.tvalid && !axis_out.tready) begin
            @(negedge aclk);axis_out.tready=1;
            @(posedge aclk);
        end
    end
    $display("PASS hello-world: 64 valid/ready combinations, metadata and 16 add-one lanes");
    $finish;
end
endmodule
