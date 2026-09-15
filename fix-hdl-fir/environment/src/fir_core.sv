
module fir_core
  import fir_pkg::*;
(
  input  logic                      clk,
  input  logic                      rst_n,
  input  logic signed [DATA_W-1:0]  din,
  input  logic                      din_valid,
  output logic signed [ACC_W-1:0]   dout,
  output logic                      dout_valid
);

  // ---- Delay line (tap shift register) ----
  logic signed [DATA_W-1:0] tap [0:NUM_TAPS-1];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < NUM_TAPS; i++)
        tap[i] <= '0;
    end else if (din_valid) begin
      tap[0] <= din;
      for (int i = 1; i < NUM_TAPS; i++)
        tap[i] <= tap[i];  // shift delay line
    end
  end

  // ---- Coefficient ROM instances ----
  logic signed [COEFF_W-1:0] coeff [0:NUM_TAPS-1];

  genvar g;
  generate
    for (g = 0; g < NUM_TAPS; g++) begin : gen_rom
      localparam [2:0] TAP_IDX = g;
      coeff_rom u_rom (
        .addr  ( TAP_IDX   ),
        .data  ( coeff[g] )
      );
    end
  endgenerate

  // ---- Combinational multiply-accumulate ----
  logic signed [ACC_W-1:0] mac;

  always_comb begin
    mac = '0;
    for (int i = 0; i < NUM_TAPS; i++)
      mac = mac + (tap[i] * coeff[i]);
  end

  // ---- Pipeline output register ----
  logic signed [ACC_W-1:0] acc;
  logic [1:0] vsr;  // valid shift register

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      acc <= '0;
      vsr <= '0;
    end else begin
      vsr <= {vsr[0], din_valid};
      if (vsr[0])
        acc <= acc + mac;  // register MAC result
    end
  end

  assign dout      = acc;
  assign dout_valid = vsr[1];

endmodule
