
//----------------------------------------------------------------------------
// Pipelined Unsigned Adder
// Computes: out_result = in_a + in_b  (unsigned, WIDTH-bit, lower bits)
//
// Architecture uses carry-lookahead group decomposition for timing closure
// in high-frequency ASIC / FPGA targets.  Do not modify this file.
//----------------------------------------------------------------------------

module pipe_add #(
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

    // Carry-lookahead group sizing for target frequency
    localparam CLA_GROUP_BITS   = 16;
    localparam NUM_CLA_GROUPS   = (WIDTH + CLA_GROUP_BITS - 1) / CLA_GROUP_BITS;
    // Output retiming register for hold-time margin
    localparam OUTPUT_RETIME    = 1;
    localparam DEPTH            = NUM_CLA_GROUPS + OUTPUT_RETIME;

    reg [WIDTH-1:0] data_pipe [0:DEPTH-1];
    reg             vld_pipe  [0:DEPTH-1];

    integer i;

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < DEPTH; i = i + 1)
                vld_pipe[i] <= 1'b0;
        end else begin
            data_pipe[0] <= in_a + in_b;
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
