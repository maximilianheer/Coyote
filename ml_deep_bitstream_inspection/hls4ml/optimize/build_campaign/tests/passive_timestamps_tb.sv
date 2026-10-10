`timescale 1ns/1ps
module passive_timestamps_tb;
    logic clk=0;
    always #2 clk=~clk;
    logic rst_n=0;
    logic [63:0] awaddr=0, araddr=0, wdata=0, rdata;
    logic [7:0] wstrb=0;
    logic awvalid=0, wvalid=0, bready=0, arvalid=0, rready=0;
    wire awready,wready,bvalid,arready,rvalid;
    wire [1:0] bresp,rresp;
    logic in_valid=0,in_ready=0,pixel_write=0,pixel_read=0,out_valid=0,out_ready=0;
    logic [63:0] in_length=0;
    passive_timestamps dut(.*);
    longint unsigned cycle=0, expected[5], reference_frame=0;
    integer observed_writes=0, observed_reads=0;
    bit reference_active=0, reference_verdict=0;

    // Independent event scoreboard: cycle of acceptance/first-valid, no DUT state.
    always @(posedge clk) begin
        if(!rst_n) begin
            cycle=0; reference_active=0; reference_verdict=0; reference_frame=0;
        end else begin
            if(in_valid && in_ready && !reference_active) begin
                reference_frame++;
                reference_active=1; reference_verdict=0;
                observed_writes=0; observed_reads=0;
                for(integer i=0;i<5;i++) expected[i]=0;
                expected[0]=cycle;
            end
            if(pixel_write) begin
                if(observed_writes==0) expected[1]=cycle;
                if(observed_writes==65535) expected[2]=cycle;
                observed_writes++;
            end
            if(pixel_read) begin
                if(observed_reads==0) expected[3]=cycle;
                observed_reads++;
            end
            if(out_valid && !reference_verdict) begin
                expected[4]=cycle; reference_verdict=1;
            end
            if(out_valid && out_ready) reference_active=0;
            cycle++;
        end
    end

    task automatic read_check(input integer index, input logic [63:0] want);
        logic [63:0] captured;
        @(negedge clk); araddr=64'(index*8); arvalid=1; rready=0;
        do @(posedge clk); while(!arready);
        @(negedge clk); arvalid=0;
        if(!rvalid || rresp!=0) $fatal(1,"missing read response");
        captured=rdata;
        if(captured!==want) $fatal(1,"CSR %0d got %h want %h",index,captured,want);
        repeat(3) begin
            @(negedge clk);
            if(!rvalid || rdata!==captured) $fatal(1,"read changed under backpressure");
        end
        rready=1; @(negedge clk); rready=0;
    endtask

    task automatic forbidden_write;
        // W before AW, then held response. Writes must not arm/reset anything.
        @(negedge clk); wvalid=1; wstrb='1; wdata='1;
        do @(posedge clk); while(!wready);
        @(negedge clk); wvalid=0;
        repeat(3) @(negedge clk);
        awvalid=1; awaddr=0;
        do @(posedge clk); while(!awready);
        @(negedge clk); awvalid=0;
        wait(bvalid);
        repeat(3) begin
            @(negedge clk);
            if(!bvalid || bresp!=2'b10) $fatal(1,"write must return held SLVERR");
        end
        bready=1; @(negedge clk); bready=0;
    endtask

    task automatic run_frame(input longint unsigned length);
        integer produced,consumed,received,beats,steps;
        produced=0; consumed=0; received=0; steps=0;
        beats=integer'((length+63)/64);
        // Valid alone does not start capture. Header acceptance does.
        @(negedge clk); in_length=length; in_valid=1; in_ready=0;
        repeat(5) @(negedge clk);
        in_ready=1; @(negedge clk); in_valid=0;
        read_check(2,reference_frame);
        read_check(4,1);
        for(integer i=1;i<5;i++) read_check(5+i,0);
        while(produced<65536 || consumed<65536 || received<beats) begin
            @(negedge clk);
            in_valid=received<beats && steps%3!=0;
            in_ready=steps%11!=0;
            pixel_write=produced<65536 && produced-consumed<32 && steps%5!=0;
            pixel_read=consumed<produced && steps%7!=0;
            @(posedge clk); #1;
            if(in_valid && in_ready) received++;
            if(pixel_write) produced++;
            if(pixel_read) consumed++;
            steps++;
        end
        @(negedge clk); in_valid=0; pixel_write=0; pixel_read=0;
        repeat(9) @(negedge clk);
        out_valid=1; out_ready=0;
        @(negedge clk);
        read_check(3,3); // active + first-valid seen; no error
        read_check(9,expected[4]);
        repeat(17) @(negedge clk);
        read_check(9,expected[4]); // first-valid survives output backpressure
        out_ready=1; @(negedge clk); out_valid=0; out_ready=0;
        forbidden_write();
        read_check(3,2); read_check(4,31);
        for(integer i=0;i<5;i++) read_check(5+i,expected[i]);
        read_check(10,65536); read_check(11,65536);
        read_check(12,length); read_check(13,64'(beats+1));
        if(!(expected[0]<expected[1] && expected[1]<=expected[3] &&
             expected[3]<expected[2] && expected[2]<expected[4]))
            $fatal(1,"timestamp order/overlap");
        $display("PASS passive frame=%0d bytes=%0d accepted_pixels=65536",reference_frame,length);
    endtask

    initial begin
        #10000000; $fatal(1,"observer timeout");
    end
    initial begin
        repeat(5) @(negedge clk); rst_n=1;
        read_check(0,64'h52534f5400010000);
        forbidden_write(); read_check(2,0); read_check(3,0);
        run_frame(0);
        run_frame(65);
        run_frame(4194241);
        // Reject a premature result; retain the failure until a new frame.
        @(negedge clk); in_length=0; in_valid=1; in_ready=1;
        @(negedge clk); in_valid=0; out_valid=1; out_ready=1;
        @(negedge clk); out_valid=0; out_ready=0;
        read_check(3,6);
        $display("PASS passive timestamps: 3 frames, stalls, read-only CSR, error gate");
        $finish;
    end
endmodule
