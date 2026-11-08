`timescale 1ns/1ps
// Deployment ABI5: independent AXI-Lite channels, immutable active-frame config.
// Slots 16..39 are event ticks; slots 48..63 are live transport counters.
module deployment_control #(
    parameter ADDR_BITS = 64,
    parameter DATA_BITS = 64,
    parameter VARIANT = 10,
    parameter logic [23:0] LAST_EVENTS = 24'hffffff
)(
    input logic clk, rst_n,
    input logic [ADDR_BITS-1:0] awaddr, araddr,
    input logic awvalid, wvalid, bready, arvalid, rready,
    input logic [DATA_BITS-1:0] wdata,
    input logic [DATA_BITS/8-1:0] wstrb,
    output logic awready, wready, bvalid, arready, rvalid,
    output logic [1:0] bresp, rresp,
    output logic [DATA_BITS-1:0] rdata,
    input logic [23:0] events,
    input logic [63:0] counters [16],
    input logic engine_ready, engine_done, engine_error,
    input logic result_valid,
    input logic [31:0] result_bits,
    output logic start, busy,
    output logic [63:0] config_words [16],
    output logic [63:0] tick
);
    logic have_aw, have_w, failed, result_seen, done;
    logic [ADDR_BITS-1:0] address;
    logic [DATA_BITS-1:0] value;
    logic [DATA_BITS/8-1:0] strobes;
    logic [63:0] origin, stamps [24];
    logic [23:0] valid_events;
    logic [31:0] score;
    wire commit = have_aw && have_w && !bvalid;
    wire go = commit && address[11:3] == 0 && strobes[0] && value[0];

    assign awready = !have_aw && !bvalid;
    assign wready = !have_w && !bvalid;
    assign arready = !rvalid;
    assign bresp = 0;
    assign rresp = 0;

    function automatic [63:0] read_register(input logic [8:0] index);
        if (index == 0)
            return {60'b0, result_seen, failed, done, busy};
        if (index == 4) return 64'h4342595400050000 | 64'(VARIANT);
        if (index == 5) return tick;
        if (index == 6) return origin;
        if (index == 7) return {40'b0, valid_events};
        if (index == 40) return {31'b0, !score[31], score};
        if (index >= 16 && index < 40) return stamps[index - 16];
        if (index >= 48 && index < 64) return counters[index - 48];
        if (index < 16) return config_words[index];
        return 0;
    endfunction

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            have_aw <= 0;
            have_w <= 0;
            bvalid <= 0;
            rvalid <= 0;
            rdata <= 0;
            address <= 0;
            value <= 0;
            strobes <= 0;
            tick <= 0;
            origin <= 0;
            start <= 0;
            busy <= 0;
            failed <= 0;
            result_seen <= 0;
            done <= 0;
            score <= 0;
            valid_events <= 0;
            for (int i = 0; i < 16; i++) config_words[i] <= 0;
            config_words[12] <= 64'd7500000000;
            config_words[13] <= 250;
            config_words[15] <= 4;
            for (int i = 0; i < 24; i++) stamps[i] <= 0;
        end else begin
            tick <= tick + 1;
            start <= 0;
            if (awvalid && awready) begin
                address <= awaddr;
                have_aw <= 1;
            end
            if (wvalid && wready) begin
                value <= wdata;
                strobes <= wstrb;
                have_w <= 1;
            end
            if (bvalid && bready) bvalid <= 0;
            if (commit) begin
                have_aw <= 0;
                have_w <= 0;
                bvalid <= 1;
                if (!busy && address[11:3] > 0 && address[11:3] < 16)
                    for (int b = 0; b < 8; b++)
                        if (strobes[b]) config_words[address[11:3]][8*b+:8] <= value[8*b+:8];
            end
            if (rvalid && rready) rvalid <= 0;
            if (arvalid && arready) begin
                rvalid <= 1;
                rdata <= DATA_BITS'(read_register(araddr[11:3]));
            end
            if (go) begin
                if (busy || !engine_ready || config_words[1] > 134217664 ||
                    config_words[8][5:0] != 0) begin
                    failed <= 1;
                end else begin
                    start <= 1;
                    busy <= 1;
                    failed <= 0;
                    done <= 0;
                    result_seen <= 0;
                    score <= 0;
                    origin <= tick;
                    valid_events <= 0;
                    for (int i = 0; i < 24; i++) stamps[i] <= 0;
                end
            end
            if (busy) begin
                for (int i = 0; i < 24; i++)
                    if (events[i] && (LAST_EVENTS[i] || !valid_events[i])) begin
                        stamps[i] <= tick;
                        valid_events[i] <= 1;
                    end
                if (result_valid) begin
                    score <= result_bits;
                    result_seen <= 1;
                end
                if (engine_error || tick - origin > config_words[12]) failed <= 1;
                // Failed transfers require a controlled reset and DMA drain.
                // Never re-arm while a previous transaction may still be live.
                if (!failed && !engine_error && engine_done && (result_seen || result_valid)) begin
                    busy <= 0;
                    done <= 1;
                end
            end
        end
    end
endmodule
