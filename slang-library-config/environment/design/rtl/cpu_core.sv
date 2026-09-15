module cpu_core
  import soc_pkg::*;
#(
  parameter int WIDTH = DWIDTH
)(
  input  logic              clk,
  input  logic              rst_n,
  input  alu_op_e           opcode,
  input  logic [3:0]        rs1,
  input  logic [3:0]        rs2,
  input  logic [3:0]        rd,
  input  logic              we,
  output logic [WIDTH-1:0]  result,
  output logic [2:0]        flags
);

  logic [WIDTH-1:0] a_data, b_data, alu_out;
  logic alu_zero, alu_carry;

  alu u_alu (
    .op     (opcode),
    .a      (a_data),
    .b      (b_data),
    .result (alu_out),
    .zero   (alu_zero),
    .carry  (alu_carry)
  );

  regfile #(
    .NUM_REGS (NREGS),
    .DATA_W   (WIDTH)
  ) u_rf (
    .clk      (clk),
    .rst_n    (rst_n),
    .rs1_addr (rs1),
    .rs2_addr (rs2),
    .wd_addr  (rd),
    .wd_data  (alu_out),
    .wd_en    (we),
    .rs1_data (a_data),
    .rs2_data (b_data)
  );

  assign result = alu_out;
  assign flags  = {alu_carry, alu_zero, 1'b0};

endmodule
