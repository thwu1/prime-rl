
//----------------------------------------------------------------------------
// Pipelined Computation Block
//
// Formula:  result = isqrt(a*a + b*b) + a*b - c
//
// All arithmetic is unsigned 32-bit (wrapping on overflow).
//
// You must use ONLY the modules from arithmetic_blocks/ for add, sub,
// multiply, and integer square-root operations.  You may not implement
// your own arithmetic.
//
// Interface follows AXI-Stream-like valid/ready handshake:
//   - Input  handshake: arg_vld / arg_rdy
//   - Output handshake: res_vld / res_rdy
//
// When the block is not busy (has capacity), arg_rdy MUST be 1;
// it must not wait for arg_vld.
//
// When there is no back-pressure, the design must accept a new set of
// inputs every clock cycle back-to-back without stalls.
//----------------------------------------------------------------------------

module compute (
    input  wire        clk,
    input  wire        rst,

    input  wire        arg_vld,
    output wire        arg_rdy,
    input  wire [31:0] a,
    input  wire [31:0] b,
    input  wire [31:0] c,

    output wire        res_vld,
    input  wire        res_rdy,
    output wire [31:0] res
);

    // ---- Implement your solution here ----

endmodule
