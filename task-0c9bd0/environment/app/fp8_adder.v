// fp8_adder.v - IEEE 754 compliant FP8 E4M3 combinational adder
//
// Format: 1 sign bit, 4 exponent bits, 3 mantissa bits, bias=7
//
// Must handle: NaN propagation, infinity arithmetic, signed zeros,
// subnormal operands, gradual underflow, all 5 rounding modes,
// overflow to infinity or max_normal per rounding mode.
//
// Port interface (DO NOT CHANGE):

module fp8_adder(
    input  wire [7:0] a,           // First FP8 operand (raw byte)
    input  wire [7:0] b,           // Second FP8 operand (raw byte)
    input  wire [2:0] rounding,    // 0=RNE, 1=RNA, 2=RU, 3=RD, 4=RZ
    output reg  [7:0] result       // FP8 result (raw byte)
);

// TODO: Implement IEEE 754 compliant FP8 addition

always @(*) begin
    result = 8'h00; // placeholder
end

endmodule
