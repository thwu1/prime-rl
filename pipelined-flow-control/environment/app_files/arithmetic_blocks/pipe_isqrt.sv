
//----------------------------------------------------------------------------
// Pipelined Integer Square Root  (floor)
// Computes: out_result = floor(sqrt(in_a))
//
// Uses non-restoring digit-recurrence algorithm.  Each pipeline stage
// resolves a fixed number of result bits.  Do not modify this file.
//----------------------------------------------------------------------------

module pipe_isqrt #(
    parameter WIDTH = 32
)(
    input  wire             clk,
    input  wire             rst,
    input  wire             in_vld,
    input  wire [WIDTH-1:0] in_a,
    output wire             out_vld,
    output wire [WIDTH-1:0] out_result
);

    // Result occupies ceil(WIDTH/2) bits.
    // Each stage resolves BITS_PER_ITER result bits.
    localparam RESULT_WIDTH   = (WIDTH + 1) / 2;
    localparam BITS_PER_ITER  = 2;
    localparam NUM_STAGES     = RESULT_WIDTH / BITS_PER_ITER;

    //----------------------------------------------------------------------
    // Behavioural model of the non-restoring integer square-root algorithm
    //----------------------------------------------------------------------

    function [WIDTH-1:0] compute_isqrt;
        input [WIDTH-1:0] val;
        reg [WIDTH-1:0] res;
        reg [WIDTH-1:0] bitmask;
        begin
            res     = {WIDTH{1'b0}};
            bitmask = {WIDTH{1'b0}};
            bitmask[WIDTH-2] = 1'b1;   // highest even bit position

            while (bitmask != 0 && bitmask > val)
                bitmask = bitmask >> 2;

            while (bitmask != 0) begin
                if (val >= res + bitmask) begin
                    val = val - res - bitmask;
                    res = (res >> 1) + bitmask;
                end else begin
                    res = res >> 1;
                end
                bitmask = bitmask >> 2;
            end

            compute_isqrt = res;
        end
    endfunction

    //----------------------------------------------------------------------
    // Pipeline registers
    //----------------------------------------------------------------------

    reg [WIDTH-1:0] data_pipe [0:NUM_STAGES-1];
    reg             vld_pipe  [0:NUM_STAGES-1];

    integer i;

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < NUM_STAGES; i = i + 1)
                vld_pipe[i] <= 1'b0;
        end else begin
            data_pipe[0] <= compute_isqrt(in_a);
            vld_pipe[0]  <= in_vld;
            for (i = 1; i < NUM_STAGES; i = i + 1) begin
                data_pipe[i] <= data_pipe[i-1];
                vld_pipe[i]  <= vld_pipe[i-1];
            end
        end
    end

    assign out_result = data_pipe[NUM_STAGES-1];
    assign out_vld    = vld_pipe[NUM_STAGES-1];

endmodule
