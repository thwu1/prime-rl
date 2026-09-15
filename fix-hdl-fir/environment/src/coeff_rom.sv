
module coeff_rom (
  input  logic [2:0]           addr,
  output logic signed [15:0]   coeff_out
);
  always_comb begin
    case (addr)
      3'd0: coeff_out = 16'sd3;
      3'd1: coeff_out = 16'sd11;
      3'd2: coeff_out = 16'sd25;
      3'd3: coeff_out = 16'sd32;
      3'd4: coeff_out = 16'sd32;
      3'd5: coeff_out = 16'sd25;
      3'd6: coeff_out = 16'sd11;
      3'd7: coeff_out = 16'sd3;
      default: coeff_out = '0;
    endcase
  end
endmodule
