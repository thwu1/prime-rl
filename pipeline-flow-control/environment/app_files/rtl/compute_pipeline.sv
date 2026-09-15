// Pipelined computation block: isqrt(a*a + b*b) + c
// Uses arithmetic sub-blocks from rtl/blackbox/
// Valid-only signaling - no flow control or backpressure
// Do not modify this file
//

module compute_pipeline (
    input  wire        clk,
    input  wire        rst,

    input  wire        in_vld,
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire [31:0] c,

    output wire        out_vld,
    output wire [31:0] result
);

    //----------------------------------------------------------
    // Stage 1: Parallel squaring  a*a and b*b
    //----------------------------------------------------------

    wire        sq_a_vld;
    wire [31:0] a_squared;

    pipe_mult #(.SEGMENT_WIDTH(16)) u_sq_a (
        .clk    (clk),
        .rst    (rst),
        .in_vld (in_vld),
        .op_a   (a),
        .op_b   (a),
        .out_vld(sq_a_vld),
        .result (a_squared)
    );

    wire        sq_b_vld;
    wire [31:0] b_squared;

    pipe_mult #(.SEGMENT_WIDTH(16)) u_sq_b (
        .clk    (clk),
        .rst    (rst),
        .in_vld (in_vld),
        .op_a   (b),
        .op_b   (b),
        .out_vld(sq_b_vld),
        .result (b_squared)
    );

    //----------------------------------------------------------
    // Registered interconnect for timing closure
    //----------------------------------------------------------

    reg [31:0] a_sq_r, b_sq_r;
    reg        sq_vld_r;

    always @(posedge clk) begin
        if (rst)
            sq_vld_r <= 1'b0;
        else begin
            a_sq_r   <= a_squared;
            b_sq_r   <= b_squared;
            sq_vld_r <= sq_a_vld;
        end
    end

    //----------------------------------------------------------
    // Stage 2: Sum of squares
    //----------------------------------------------------------

    wire        sum_vld;
    wire [31:0] sum_of_squares;

    pipe_add u_sum (
        .clk    (clk),
        .rst    (rst),
        .in_vld (sq_vld_r),
        .op_a   (a_sq_r),
        .op_b   (b_sq_r),
        .out_vld(sum_vld),
        .result (sum_of_squares)
    );

    //----------------------------------------------------------
    // Stage 3: Integer square root
    //----------------------------------------------------------

    wire        sqrt_vld;
    wire [31:0] sqrt_res;

    pipe_isqrt #(.ITERS_PER_STAGE(4)) u_sqrt (
        .clk    (clk),
        .rst    (rst),
        .in_vld (sum_vld),
        .operand(sum_of_squares),
        .out_vld(sqrt_vld),
        .result (sqrt_res)
    );

    //----------------------------------------------------------
    // Data alignment: delay c to arrive at the final adder
    // at the same time as the sqrt output
    //----------------------------------------------------------

    localparam C_ALIGN_DEPTH = 9;

    reg [31:0] c_sr [0:C_ALIGN_DEPTH-1];

    integer i;
    always @(posedge clk) begin
        c_sr[0] <= c;
        for (i = 1; i < C_ALIGN_DEPTH; i = i + 1)
            c_sr[i] <= c_sr[i-1];
    end

    //----------------------------------------------------------
    // Stage 4: Final addition   result = isqrt(...) + c
    //----------------------------------------------------------

    pipe_add u_final_add (
        .clk    (clk),
        .rst    (rst),
        .in_vld (sqrt_vld),
        .op_a   (sqrt_res),
        .op_b   (c_sr[C_ALIGN_DEPTH-1]),
        .out_vld(out_vld),
        .result (result)
    );

endmodule
