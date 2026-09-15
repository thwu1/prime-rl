// Round-robin arbiter using priority encoders
`include "xbar_defs.svh"

module round_robin_arb
  import xbar_pkg::*;
#(
  parameter int NUM_REQ = 4
)(
  input  logic                          clk,
  input  logic                          rst_n,
  input  logic [NUM_REQ-1:0]            req,
  output logic [NUM_REQ-1:0]            grant,
  output logic                          valid
);

  logic [NUM_REQ-1:0] mask_q;
  logic [NUM_REQ-1:0] masked_req;
  logic [$clog2(NUM_REQ)-1:0] masked_idx, raw_idx;
  logic masked_valid, raw_valid;

  assign masked_req = req & mask_q;
  assign valid = |req;

  // Priority encoder for masked requests
  priority_enc #(.WIDTH(NUM_REQ)) u_masked_enc (
    .req   (masked_requests),
    .idx   (masked_idx),
    .valid (masked_valid)
  );

  // Priority encoder for raw requests (fallback)
  priority_enc #(.WIDTH(NUM_REQ)) u_raw_enc (
    .req   (req),
    .idx   (raw_idx),
    .valid (raw_valid)
  );

  // Generate one-hot grant from selected index
  logic [$clog2(NUM_REQ)-1:0] sel_idx;
  assign sel_idx = masked_valid ? masked_idx : raw_idx;

  always_comb begin
    grant = '0;
    if (valid)
      grant[sel_idx] = 1'b1;
  end

  // Update mask: rotate priority after each grant
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      mask_q <= '1;
    else if (valid) begin
      if (grant[NUM_REQ-1])
        mask_q <= '1;
      else
        mask_q <= ~((grant << 1) - 1'b1);
    end
  end

endmodule
