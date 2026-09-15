
//----------------------------------------------------------------------------
// Pipelined Unsigned Subtractor
// Computes: out_result = in_a - in_b  (unsigned, WIDTH-bit, wrapping)
//
// Architecture mirrors pipe_add with borrow-propagation group decomposition.
// Do not modify this file.
//----------------------------------------------------------------------------

module pipe_sub #(
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

    // Borrow-propagation group sizing (mirrors CLA adder)
    localparam BPG_GROUP_BITS   = 16;
    localparam NUM_BPG_GROUPS   = (WIDTH + BPG_GROUP_BITS - 1) / BPG_GROUP_BITS;
    // Output retiming register
    localparam OUTPUT_RETIME    = 1;
    localparam DEPTH            = NUM_BPG_GROUPS + OUTPUT_RETIME;

    reg [WIDTH-1:0] data_pipe [0:DEPTH-1];
    reg             vld_pipe  [0:DEPTH-1];

    integer i;

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < DEPTH; i = i + 1)
                vld_pipe[i] <= 1'b0;
        end else begin
            data_pipe[0] <= in_a - in_b;
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
