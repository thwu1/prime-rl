module alu
  import soc_pkg::*;
(
  input  alu_op_e             op,
  input  logic [DWIDTH-1:0]   a,
  input  logic [DWIDTH-1:0]   b,
  output logic [DWIDTH-1:0]   result,
  output logic                zero,
  output logic                carry
);

  always_comb begin
    carry = 1'b0;
    case (op)
      ALU_ADD: {carry, result} = a + b;
      ALU_SUB: {carry, result} = a - b;
      ALU_AND: result = a & b;
      ALU_OR:  result = a | b;
      ALU_XOR: result = a ^ b;
      ALU_SLL: result = a << b[4:0];
      ALU_SRL: result = a >> b[4:0];
      default: result = '0;
    endcase
    zero = (result == '0);
  end

endmodule
