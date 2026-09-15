// Address decoder - routes requests based on upper address bits
module addr_decoder
  import xbar_pkg::*;
#(
  parameter int NUM_OUTPUTS = 4,
  parameter int ADDR_W      = ADDR_WIDTH
)(
  input  logic [ADDR_W-1:0]             addr,
  output logic [$clog2(NUM_OUTPUTS)-1:0] sel,
  output logic                           valid
);

  localparam int SEL_W = $clog2(NUM_OUTPUTS);

  // Decode slave select from upper address bits
  assign sel = addr[15:14];
  assign valid = 1'b1;

endmodule
