
module fir_engine
  import fir_pkg::*;
(
  input  logic                        clk,
  input  logic                        rst_n,
  input  logic                        cfg_wr,
  input  logic [2:0]                  cfg_addr,
  input  logic signed [COEFF_W-1:0]   cfg_data,
  input  logic                        cfg_done,
  input  logic signed [DATA_W-1:0]    din,
  input  logic                        din_valid,
  output logic signed [ACC_W-1:0]     dout,
  output logic                        dout_valid
);

  // TODO: Implement the FIR filter engine internals.

endmodule
