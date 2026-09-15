// m_ref.v - Reference implementations of RV32IM M-extension instructions
// Adapted from riscv-formal instruction models (YosysHQ/riscv-formal)
// These models define the authoritative expected behavior for each
// M-extension instruction, including edge cases.
//
// Compile with: iverilog -o m_ref_sim m_ref.v tb_m_ext.v
// Run with:     vvp m_ref_sim

// MUL: rd = (rs1 * rs2)[31:0]
// Lower 32 bits of the product; result is identical for signed/unsigned.
module mul_ref(input [31:0] rs1, input [31:0] rs2, output [31:0] rd);
    wire [63:0] product = {32'b0, rs1} * {32'b0, rs2};
    assign rd = product[31:0];
endmodule

// MULH: rd = (signed(rs1) * signed(rs2))[63:32]
// Upper 32 bits of the full signed product.
module mulh_ref(input [31:0] rs1, input [31:0] rs2, output [31:0] rd);
    wire signed [63:0] product =
        $signed({{32{rs1[31]}}, rs1}) * $signed({{32{rs2[31]}}, rs2});
    assign rd = product[63:32];
endmodule

// MULHU: rd = (unsigned(rs1) * unsigned(rs2))[63:32]
// Upper 32 bits of the full unsigned product.
module mulhu_ref(input [31:0] rs1, input [31:0] rs2, output [31:0] rd);
    wire [63:0] product = {32'b0, rs1} * {32'b0, rs2};
    assign rd = product[63:32];
endmodule

// MULHSU: rd = (signed(rs1) * unsigned(rs2))[63:32]
// Upper 32 bits of signed-by-unsigned product.
// rs1 is sign-extended; rs2 is zero-extended with a leading 0 bit
// to remain non-negative in a signed multiplication context.
module mulhsu_ref(input [31:0] rs1, input [31:0] rs2, output [31:0] rd);
    wire signed [63:0] product =
        $signed({{32{rs1[31]}}, rs1}) * $signed({1'b0, rs2});
    assign rd = product[63:32];
endmodule

// DIV: rd = signed(rs1) / signed(rs2), truncated toward zero.
// Special cases per RISC-V spec:
//   - Division by zero: rd = -1 (0xFFFFFFFF)
//   - Signed overflow (-2^31 / -1): rd = -2^31 (0x80000000)
module div_ref(input [31:0] rs1, input [31:0] rs2, output reg [31:0] rd);
    reg signed [31:0] s1, s2;
    always @(*) begin
        s1 = rs1;
        s2 = rs2;
        if (rs2 == 32'd0)
            rd = 32'hFFFFFFFF;
        else if (rs1 == 32'h80000000 && rs2 == 32'hFFFFFFFF)
            rd = 32'h80000000;
        else
            rd = s1 / s2;
    end
endmodule

// DIVU: rd = unsigned(rs1) / unsigned(rs2)
// Division by zero: rd = 0xFFFFFFFF
module divu_ref(input [31:0] rs1, input [31:0] rs2, output reg [31:0] rd);
    always @(*) begin
        if (rs2 == 32'd0)
            rd = 32'hFFFFFFFF;
        else
            rd = rs1 / rs2;
    end
endmodule

// REM: rd = signed(rs1) % signed(rs2), sign matches dividend.
// Special cases:
//   - Division by zero: rd = rs1 (the dividend)
//   - Signed overflow (-2^31 % -1): rd = 0
module rem_ref(input [31:0] rs1, input [31:0] rs2, output reg [31:0] rd);
    reg signed [31:0] s1, s2;
    always @(*) begin
        s1 = rs1;
        s2 = rs2;
        if (rs2 == 32'd0)
            rd = rs1;
        else if (rs1 == 32'h80000000 && rs2 == 32'hFFFFFFFF)
            rd = 32'd0;
        else
            rd = s1 % s2;
    end
endmodule

// REMU: rd = unsigned(rs1) % unsigned(rs2)
// Division by zero: rd = rs1 (the dividend)
module remu_ref(input [31:0] rs1, input [31:0] rs2, output reg [31:0] rd);
    always @(*) begin
        if (rs2 == 32'd0)
            rd = rs1;
        else
            rd = rs1 % rs2;
    end
endmodule
