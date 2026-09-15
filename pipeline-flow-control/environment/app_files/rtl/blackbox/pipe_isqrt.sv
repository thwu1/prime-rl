// Pipelined integer square root (non-restoring algorithm model)
// Iterations grouped into pipeline stages for throughput
// Do not modify this file
//

module pipe_isqrt #(
    parameter ITERS_PER_STAGE = 2
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        in_vld,
    input  wire [31:0] operand,
    output wire        out_vld,
    output wire [31:0] result
);

    localparam OPERAND_WIDTH    = 32;
    localparam TOTAL_ITERATIONS = OPERAND_WIDTH / 2;
    localparam RESULT_WIDTH     = OPERAND_WIDTH / 2;
    localparam GUARD_BITS       = 2;
    localparam PIPE_DEPTH       = TOTAL_ITERATIONS / ITERS_PER_STAGE;

    reg [31:0] data_pipe [0:PIPE_DEPTH-1];
    reg [PIPE_DEPTH-1:0] vld_pipe;

    // Combinational isqrt for functional modeling
    function [31:0] isqrt_comb;
        input [31:0] n;
        reg [31:0] x, x1;
        integer i;
        begin
            if (n <= 1) begin
                isqrt_comb = n;
            end else begin
                x = n;
                x1 = (x + 1) / 2;
                for (i = 0; i < 36; i = i + 1) begin
                    if (x1 < x) begin
                        x = x1;
                        x1 = (x + n / x) / 2;
                    end
                end
                isqrt_comb = x;
            end
        end
    endfunction

    integer s;
    always @(posedge clk) begin
        if (rst) begin
            vld_pipe <= {PIPE_DEPTH{1'b0}};
        end else begin
            data_pipe[0] <= isqrt_comb(operand);
            vld_pipe[0]  <= in_vld;
            for (s = 1; s < PIPE_DEPTH; s = s + 1) begin
                data_pipe[s] <= data_pipe[s-1];
                vld_pipe[s]  <= vld_pipe[s-1];
            end
        end
    end

    assign out_vld = vld_pipe[PIPE_DEPTH-1];
    assign result  = data_pipe[PIPE_DEPTH-1];

endmodule
