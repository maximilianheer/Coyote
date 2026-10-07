// AXI-Lite registers and counters for one outstanding FPGA-initiated card read.
// Address offsets are 64-bit word indices; timestamps use the aclk domain.
module benchmark_control #(
    parameter integer ADDR_BITS = 64,
    parameter integer DATA_BITS = 64,
    parameter integer INSTRUMENT = 1,
    parameter integer VARIANT = 1
)(
    input logic clk, rst_n,
    input logic [ADDR_BITS-1:0] awaddr, araddr,
    input logic awvalid, wvalid, bready, arvalid, rready,
    input logic [DATA_BITS-1:0] wdata,
    input logic [DATA_BITS/8-1:0] wstrb,
    output logic awready, wready, bvalid, arready, rvalid,
    output logic [1:0] bresp, rresp,
    output logic [DATA_BITS-1:0] rdata,
    output logic request_valid,
    input logic request_ready, read_complete,
    output logic [63:0] source_addr,
    output logic [31:0] source_bytes,
    output logic [31:0] source_pid,
    input logic in_valid, in_ready,
    input logic [2:0] phase,
    input logic [3:0] stage_events,
    input logic [31:0] produced_tokens,
    input logic result_valid,
    input logic [31:0] result_bits,
    output logic busy
);
    logic have_aw, have_w;
    logic [ADDR_BITS-1:0] saved_aw;
    logic [DATA_BITS-1:0] saved_w;
    logic [DATA_BITS/8-1:0] saved_strb;
    logic done, error_flag, started, first_seen;
    logic [63:0] tick, origin, first_tick, last_tick, decision_tick, ack_tick;
    logic [63:0] phase_ticks[0:3];
    logic [63:0] starve, blocked_input, beats;
    logic [63:0] phase_start[0:3];
    logic [3:0] phase_seen;
    logic [31:0] result;
    logic ack_seen, payload_seen;
    logic [3:0] event_baseline, event_seen;
    logic [63:0] event_tick[0:3];
    logic [63:0] payload_first, payload_last;
    logic [31:0] token_count;
    wire accepted_request = request_valid && request_ready;
    wire [63:0] elapsed = started ? tick-origin : 0;
    wire commit_write = have_aw && have_w && !bvalid;
    wire go = commit_write && saved_aw[11:3] == 0 && saved_strb[0] && saved_w[0];
    assign awready = !have_aw && !bvalid;
    assign wready = !have_w && !bvalid;
    assign arready = !rvalid;
    assign bresp = 2'b00;
    assign rresp = 2'b00;

    function automatic [63:0] read_reg(input logic [8:0] index);
        case(index)
          0: read_reg = {57'b0, phase, 1'b0, error_flag, done, busy};
          1: read_reg = source_addr;
          2: read_reg = {32'b0, source_bytes};
          3: read_reg = {32'b0, source_pid};
          4: read_reg = origin;
          5: read_reg = first_tick;
          6: read_reg = last_tick;
          7: read_reg = phase_ticks[1];
          8: read_reg = phase_ticks[2];
          9: read_reg = phase_ticks[3];
          10: read_reg = starve;
          11: read_reg = blocked_input;
          12: read_reg = beats;
          13: read_reg = decision_tick;
          14: read_reg = {32'b0, result};
          15: read_reg = (VARIANT == 6 ? 64'h4342595400020000 : 64'h4342595400010000) | 64'(VARIANT);
          16: read_reg = phase_start[1];
          17: read_reg = phase_start[2];
          18: read_reg = phase_start[3];
          19: read_reg = ack_tick;
          // ABI v2 extension; legacy offsets and signature remain for IDs 1..5.
          20: read_reg = {56'b0, payload_seen, ack_seen, done, 1'b0, event_seen};
          21: read_reg = payload_first;
          22: read_reg = payload_last;
          23: read_reg = event_tick[0]; // preprocessing after length header
          24: read_reg = event_tick[1]; // final token produced
          25: read_reg = event_tick[2]; // CNN task start, not first pixel read
          26: read_reg = event_tick[3]; // logit read by publication task
          27: read_reg = {32'b0, token_count};
          default: read_reg = 0;
        endcase
    endfunction

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            have_aw <= 0; have_w <= 0; bvalid <= 0; rvalid <= 0; rdata <= 0;
            saved_aw <= 0; saved_w <= 0; saved_strb <= 0;
            source_addr <= 0; source_bytes <= 0; source_pid <= 0;
            request_valid <= 0; busy <= 0; done <= 0; error_flag <= 0;
            started <= 0; first_seen <= 0; tick <= 0; origin <= 0;
            first_tick <= 0; last_tick <= 0; decision_tick <= 0; ack_tick <= 0;
            starve <= 0; blocked_input <= 0; beats <= 0; result <= 0; phase_seen <= 0;
            ack_seen <= 0; payload_seen <= 0; event_baseline <= 0; event_seen <= 0;
            payload_first <= 0; payload_last <= 0; token_count <= 0;
            for (int i=0; i<4; i++) event_tick[i] <= 0;
            for (int i=0; i<4; i++) begin phase_ticks[i] <= 0; phase_start[i] <= 0; end
        end else begin
            tick <= tick + 1;
            if (awready && awvalid) begin have_aw <= 1; saved_aw <= awaddr; end
            if (wready && wvalid) begin have_w <= 1; saved_w <= wdata; saved_strb <= wstrb; end
            if (bvalid && bready) bvalid <= 0;
            if (commit_write) begin
                have_aw <= 0; have_w <= 0; bvalid <= 1;
                if (!busy) begin
                    for (int b=0; b<8; b++) if (saved_strb[b]) begin
                        case (saved_aw[11:3])
                          1: source_addr[b*8+:8] <= saved_w[b*8+:8];
                          2: if (b<4) source_bytes[b*8+:8] <= saved_w[b*8+:8];
                          3: if (b<4) source_pid[b*8+:8] <= saved_w[b*8+:8];
                          default: begin end
                        endcase
                    end
                end
            end
            if (rvalid && rready) rvalid <= 0;
            if (arvalid && arready) begin rvalid <= 1; rdata <= DATA_BITS'(read_reg(araddr[11:3])); end
            if (go) begin
                if (busy || source_bytes == 0) error_flag <= 1;
                else begin
                    busy <= 1; done <= 0; error_flag <= 0; started <= 0;
                    request_valid <= 1; first_seen <= 0; phase_seen <= 0;
                    ack_seen <= 0; payload_seen <= 0; event_baseline <= stage_events; event_seen <= 0;
                    payload_first <= 0; payload_last <= 0; token_count <= 0;
                    for (int i=0; i<4; i++) event_tick[i] <= 0;
                    first_tick <= 0; last_tick <= 0; decision_tick <= 0; ack_tick <= 0;
                    starve <= 0; blocked_input <= 0; beats <= 0; result <= 0;
                    for (int i=0; i<4; i++) begin phase_ticks[i] <= 0; phase_start[i] <= 0; end
                end
            end
            if (request_valid && request_ready) begin
                request_valid <= 0; started <= 1; origin <= tick;
            end
            if ((started || accepted_request) && busy) begin
                if (INSTRUMENT != 0 && !done) begin
                    if (VARIANT == 6) begin
                        for (int i=0; i<4; i++) begin
                            if (!event_seen[i] && stage_events[i] != event_baseline[i]) begin
                                event_seen[i] <= 1;
                                event_tick[i] <= elapsed;
                            end
                        end
                        token_count <= produced_tokens;
                        // Stop counting transport stalls after all aligned beats.
                        if (beats < (({32'b0, source_bytes}+63)>>6)) begin
                            if (in_ready && !in_valid) starve <= starve + 1;
                            if (in_valid && !in_ready) blocked_input <= blocked_input + 1;
                        end
                    end else begin
                        if (phase < 4) begin
                            phase_ticks[phase[1:0]] <= phase_ticks[phase[1:0]] + 1;
                            if (!phase_seen[phase[1:0]]) begin
                                phase_seen[phase[1:0]] <= 1;
                                phase_start[phase[1:0]] <= elapsed;
                            end
                        end
                        if (in_ready && !in_valid && (!first_seen || phase == 1)) starve <= starve + 1;
                        if (in_valid && !in_ready) blocked_input <= blocked_input + 1;
                    end
                    if (in_valid && in_ready) begin
                        if (!first_seen) begin first_seen <= 1; first_tick <= elapsed; end
                        last_tick <= elapsed; beats <= beats + 1;
                        // Raw frame beat zero is the length header, not payload.
                        if (beats != 0) begin
                            if (!payload_seen) begin payload_seen <= 1; payload_first <= elapsed; end
                            payload_last <= elapsed;
                        end
                    end
                end
                if (read_complete && !ack_seen) begin ack_tick <= elapsed; ack_seen <= 1; end
                if (result_valid && !done) begin
                    result <= result_bits; decision_tick <= elapsed; done <= 1;
                end
                // Capture result and acknowledgement independently in either order.
                // A new request is safe only after both have arrived.
                if ((done || result_valid) && (ack_seen || read_complete)) begin
                    busy <= 0; started <= 0;
                end
            end
        end
    end
endmodule
