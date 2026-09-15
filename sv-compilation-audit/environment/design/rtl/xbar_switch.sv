// Crossbar switch matrix - routes requests from inputs to outputs
`include "xbar_defs.svh"

module xbar_switch
#(
  parameter int NUM_INP  = 4,
  parameter int NUM_OUT  = 4,
  parameter int DATA_W   = 32
)(
  input  logic                          clk,
  input  logic                          rst_n,
  input  xbar_req_t                     inp_req  [NUM_INP],
  output xbar_resp_t                    inp_resp [NUM_INP],
  output xbar_req_t                     out_req  [NUM_OUT],
  input  xbar_resp_t                    out_resp [NUM_OUT],
  input  logic [$clog2(NUM_OUT)-1:0]    route    [NUM_INP]
);

  // Crossbar routing logic: forward requests to designated outputs
  always_comb begin
    for (int j = 0; j < NUM_OUT; j++)
      out_req[j] = '0;
    for (int i = 0; i < NUM_INP; i++)
      out_req[route[i]] = inp_req[i];
  end

  // Response routing: reverse path from outputs back to inputs
  always_comb begin
    for (int i = 0; i < NUM_INP; i++)
      inp_resp[i] = out_resp[route[i]];
  end

endmodule
