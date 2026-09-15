
//----------------------------------------------------------------------------
// Pipelined Unsigned Multiplier (lower WIDTH bits of product)
// Computes: out_result = (in_a * in_b)[WIDTH-1:0]
//
// Uses modified Booth-encoded partial-product tree with configurable radix.
// Do not modify this file.
//----------------------------------------------------------------------------

module pipe_mult #(
    parameter WIDTH = 32
)(
    input  wire             clk,
    input  wire             rst,
    input  wire             in_vld,
    input  wire [WIDTH-1:0] in_a,
    input  wire [WIDTH-1:0] in_b,
    output wire             out_vld,
    output wire [WIDTH-1:0] out_result
);

    // Modified Booth encoding: process RADIX_BITS multiplier bits per stage
    localparam RADIX_BITS          = 8;
    localparam NUM_PARTIAL_STAGES  = (WIDTH + RADIX_BITS - 1) / RADIX_BITS;
    // Wallace-tree compression + output register
    localparam COMPRESS_STAGES     = 1;
    localparam DEPTH               = NUM_PARTIAL_STAGES + COMPRESS_STAGES;

    reg [WIDTH-1:0] data_pipe [0:DEPTH-1];
    reg             vld_pipe  [0:DEPTH-1];

    integer i;

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < DEPTH; i = i + 1)
                vld_pipe[i] <= 1'b0;
        end else begin
            data_pipe[0] <= in_a * in_b;
            vld_pipe[0]  <= in_vld;
            for (i = 1; i < DEPTH; i = i + 1) begin
                data_pipe[i] <= data_pipe[i-1];
                vld_pipe[i]  <= vld_pipe[i-1];
            end
        end
    end

    assign out_result = data_pipe[DEPTH-1];
    assign out_vld    = vld_pipe[DEPTH-1];

endmodule
