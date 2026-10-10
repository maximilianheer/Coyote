// Full-CNN test add-on; original input driver and result checks stay unchanged.
passive_timestamps observer (
    .clk(ap_clk),.rst_n(ap_rst_n),
    .awaddr(64'b0),.araddr(64'b0),.awvalid(1'b0),.wvalid(1'b0),
    .bready(1'b1),.arvalid(1'b0),.rready(1'b1),.wdata(64'b0),.wstrb(8'b0),
    .awready(),.wready(),.bvalid(),.arready(),.rvalid(),.bresp(),.rresp(),.rdata(),
    .in_valid(data_in_TVALID),.in_ready(data_in_TREADY),.in_length(data_in_TDATA[63:0]),
    .pixel_write(observer_pixel_write),.pixel_read(observer_pixel_read),
    .out_valid(data_out_TVALID),.out_ready(data_out_TREADY)
);
longint unsigned passive_cycle=0, passive_expected[5];
integer passive_writes=0,passive_reads=0;
bit passive_active=0,passive_verdict=0;

function automatic [15:0] passive_expected_pixel(input integer index);
    longint unsigned raw_index;
    integer raw_byte;
    raw_index=n>65536 ? 64'(index)*64'(n-1)/65535 : 64'(index);
    raw_byte=raw_index<64'(n) ? integer'((raw_index*131+raw_index/11+17)&255) : 0;
    return 16'(((255-raw_byte)*1024)/255);
endfunction

always @(posedge ap_clk) begin
    if(!ap_rst_n) begin
        passive_cycle=0;passive_active=0;passive_verdict=0;
    end else begin
        // Compare exported events with the actual internal FIFO operations.
        if(observer_pixel_write!==dut.bitstream_input_U.push ||
           observer_pixel_read!==dut.bitstream_input_U.pop)
            $fatal(1,"passive event differs from internal FIFO acceptance");
        if(data_in_TVALID && data_in_TREADY && !passive_active) begin
            passive_active=1;passive_verdict=0;passive_writes=0;passive_reads=0;
            for(integer i=0;i<5;i++)passive_expected[i]=0;
            passive_expected[0]=passive_cycle;
        end
        if(dut.bitstream_input_U.push) begin
            if(!passive_active || passive_writes>=65536) $fatal(1,"unexpected produced pixel");
            if(dut.bitstream_input_U.if_din!==passive_expected_pixel(passive_writes))
                $fatal(1,"preprocessing pixel mismatch index=%0d",passive_writes);
            if(passive_writes==0)passive_expected[1]=passive_cycle;
            if(passive_writes==65535)passive_expected[2]=passive_cycle;
            passive_writes++;
        end
        if(dut.bitstream_input_U.pop) begin
            if(!passive_active || passive_reads>=65536) $fatal(1,"unexpected consumed pixel");
            if(dut.bitstream_input_U.if_dout!==passive_expected_pixel(passive_reads))
                $fatal(1,"CNN input pixel mismatch index=%0d",passive_reads);
            if(passive_reads==0)passive_expected[3]=passive_cycle;
            passive_reads++;
        end
        if(data_out_TVALID && !passive_verdict) begin
            passive_expected[4]=passive_cycle;passive_verdict=1;
        end
        if(data_out_TVALID && data_out_TREADY)passive_active=0;
        passive_cycle++;
    end
end

task check_passive_frame;
    if(observer.read_reg(2)!==64'(frame+1) || observer.read_reg(3)!==64'd2 ||
       observer.read_reg(4)!==64'd31) $fatal(1,"invalid passive capture status");
    for(integer i=0;i<5;i++)begin
        if(observer.read_reg(9'(5+i))!==passive_expected[i])
            $fatal(1,"passive timestamp %0d got %0d want %0d",i,observer.read_reg(9'(5+i)),passive_expected[i]);
    end
    if(observer.read_reg(10)!==65536 || observer.read_reg(11)!==65536 ||
       observer.read_reg(12)!==64'(n) || observer.read_reg(13)!==64'(1+(n+63)/64))
        $fatal(1,"passive capture counts");
    if(!(passive_expected[0]<passive_expected[1] && passive_expected[1]<=passive_expected[3] &&
         passive_expected[3]<passive_expected[2] && passive_expected[2]<passive_expected[4]))
        $fatal(1,"missing streaming overlap / timestamp order");
    $display("PASS production passive frame=%0d bytes=%0d exact_pixels=65536",frame,n);
endtask
