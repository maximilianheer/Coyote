`timescale 1ns/1ps
// Bounded 64KiB bursts; native Coyote splits each burst into PMTU requests.
// A burst retires after its data and both native completions have arrived.
module hbm_forward(
    input logic clk, rst_n, start,
    input logic [63:0] length, hbm_base, gpu_base,
    output logic rd_valid, wr_valid,
    input logic rd_ready, wr_ready,
    output logic [63:0] rd_address, wr_address,
    output logic [27:0] request_length,
    input logic input_valid,
    output logic input_ready,
    input logic [511:0] input_data,
    output logic output_valid,
    input logic output_ready,
    output logic [511:0] output_data,
    output logic [63:0] output_keep,
    output logic output_last,
    input logic rd_complete, wr_complete,
    output logic idle, done, error,
    output logic [63:0] bytes_sent, chunks_completed
);
    typedef enum logic [1:0] {IDLE, REQUEST, TRANSFER, COMPLETE} state_t;
    state_t state;
    logic read_posted, write_posted, read_ack, write_ack;
    logic [63:0] offset;
    logic [16:0] chunk_length, chunk_sent;
    wire transfer = output_valid && output_ready;
    wire [16:0] remaining = chunk_length - chunk_sent;
    assign rd_valid = state == REQUEST && !read_posted;
    assign wr_valid = state == REQUEST && !write_posted;
    assign rd_address = hbm_base + offset;
    assign wr_address = gpu_base + 64 + offset;
    assign request_length = {11'b0, chunk_length};
    assign output_data = input_data;
    assign output_valid = input_valid && state == TRANSFER && chunk_sent < chunk_length;
    assign input_ready = output_ready && state == TRANSFER && chunk_sent < chunk_length;
    assign output_last = remaining <= 64;
    assign output_keep = remaining >= 64 ? ~64'b0 : (64'b1 << remaining) - 1;
    assign idle = state == IDLE || state == COMPLETE;
    assign done = state == COMPLETE;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state <= IDLE;
            read_posted <= 0;
            write_posted <= 0;
            read_ack <= 0;
            write_ack <= 0;
            offset <= 0;
            chunk_length <= 0;
            chunk_sent <= 0;
            bytes_sent <= 0;
            chunks_completed <= 0;
            error <= 0;
        end else if (start && idle) begin
            offset <= 0;
            chunk_length <= length > 65536 ? 17'd65536 : length[16:0];
            chunk_sent <= 0;
            bytes_sent <= 0;
            chunks_completed <= 0;
            read_posted <= 0;
            write_posted <= 0;
            read_ack <= 0;
            write_ack <= 0;
            error <= 0;
            state <= length == 0 ? COMPLETE : REQUEST;
        end else begin
            if (rd_complete) read_ack <= 1;
            if (wr_complete) write_ack <= 1;
            if (rd_complete && (!read_posted || read_ack)) error <= 1;
            if (wr_complete && (!write_posted || write_ack)) error <= 1;
            case (state)
                REQUEST: begin
                    if (rd_valid && rd_ready) read_posted <= 1;
                    if (wr_valid && wr_ready) write_posted <= 1;
                    if ((read_posted || (rd_valid && rd_ready)) &&
                        (write_posted || (wr_valid && wr_ready))) state <= TRANSFER;
                end
                TRANSFER: begin
                    if (transfer) begin
                        chunk_sent <= chunk_sent + (remaining >= 64 ? 17'd64 : remaining);
                        bytes_sent <= bytes_sent + (remaining >= 64 ? 64'd64 : {47'b0, remaining});
                    end
                    if (chunk_sent == chunk_length && read_ack && write_ack) begin
                        chunks_completed <= chunks_completed + 1;
                        if (offset + chunk_length == length) state <= COMPLETE;
                        else begin
                            offset <= offset + chunk_length;
                            chunk_length <= length - offset - chunk_length > 65536
                                ? 17'd65536 : 17'(length - offset - chunk_length);
                            chunk_sent <= 0;
                            read_posted <= 0;
                            write_posted <= 0;
                            read_ack <= 0;
                            write_ack <= 0;
                            state <= REQUEST;
                        end
                    end
                end
                default: begin end
            endcase
        end
    end
endmodule
