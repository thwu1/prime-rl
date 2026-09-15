
module fir_top
  import fir_pkg::*;
(
  input  logic                        clk,
  input  logic                        rst_n,
  // Coefficient configuration interface
  input  logic                        cfg_wr,
  input  logic [2:0]                  cfg_addr,
  input  logic signed [COEFF_W-1:0]   cfg_data,
  input  logic                        cfg_done,
  // Data streaming interface
  input  logic signed [DATA_W-1:0]    s_data,
  input  logic                        s_valid,
  output logic signed [ACC_W-1:0]     m_data,
  output logic                        m_valid
);

  fir_engine u_engine (
    .clk       ( clk     ),
    .rst_n     ( rst_n   ),
    .cfg_wr    ( cfg_wr  ),
    .cfg_addr  ( cfg_addr),
    .cfg_data  ( cfg_data),
    .cfg_done  ( cfg_done),
    .din       ( s_data  ),
    .din_valid ( s_valid ),
    .dout      ( m_data  ),
    .dout_valid( m_valid )
  );

endmodule
