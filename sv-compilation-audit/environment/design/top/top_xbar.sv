// Top-level crossbar subsystem with arbitration
`include "xbar_defs.svh"

module top_xbar
  import xbar_pkg::*;
#(
  parameter int N_MASTERS = NUM_MASTERS,
  parameter int N_SLAVES  = NUM_SLAVES
)(
  input  logic        clk,
  input  logic        rst_n,
  input  xbar_req_t   mst_req  [N_MASTERS],
  output xbar_resp_t  mst_resp [N_MASTERS],
  output xbar_req_t   slv_req  [N_SLAVES],
  input  xbar_resp_t  slv_resp [N_SLAVES]
);

  // Address decoding: per-master route computation
  logic [$clog2(N_SLAVES)-1:0] route [N_MASTERS];
  logic route_valid [N_MASTERS];

  genvar h;
  generate
    for (h = 0; h < N_MASTERS; h++) begin : gen_dec
      addr_decoder #(
        .NUM_OUTPUTS(N_SLAVES),
        .ADDR_W(ADDR_WIDTH)
      ) u_dec (
        .addr  (mst_req[h].address),
        .sel   (route[h]),
        .valid (route_valid[h])
      );
    end
  endgenerate

  // Per-slave arbitration request vectors
  logic [N_MASTERS-1:0] arb_req   [N_SLAVES];
  logic [N_MASTERS-1:0] arb_grant [N_SLAVES];
  logic                 arb_valid [N_SLAVES];

  always_comb begin
    for (int j = 0; j < N_SLAVES; j++) begin
      arb_req[j] = '0;
      for (int i = 0; i < N_MASTERS; i++) begin
        if (route[i] == j[$clog2(N_SLAVES)-1:0])
          arb_req[j][i] = 1'b1;
      end
    end
  end

  // Instantiate per-slave round-robin arbiters
  genvar g;
  generate
    for (g = 0; g < N_SLAVES; g++) begin : gen_arb
      round_robin_arb #(
        .NUM_REQ(N_MASTERS)
      ) u_arb (
        .clk   (clk),
        .rst_n (rst_n),
        .req   (arb_req[g]),
        .grant (arb_grant[g]),
        .valid (arb_valid[g])
      );
    end
  endgenerate

  // Crossbar switch fabric
  xbar_switch #(
    .NUM_INP (N_MASTERS),
    .NUM_OUT (N_SLAVES),
    .DATA_W  (DATA_WIDTH)
  ) u_xbar (
    .clk      (clk),
    .rst_n    (rst_n),
    .inp_req  (mst_req),
    .inp_resp (mst_resp),
    .out_req  (slv_req),
    .out_resp (slv_resp),
    .route    (route)
  );

endmodule
