// Crossbar switch package - type definitions and utility functions
package xbar_pkg;

  parameter int NUM_MASTERS = 4;
  parameter int NUM_SLAVES  = 4;
  parameter int DATA_WIDTH  = 32;
  parameter int ADDR_WIDTH  = 16;
  parameter int ID_WIDTH    = 4;

  typedef enum logic [2:0] {
    CMD_READ    = 3'b000,
    CMD_WRITE   = 3'b001,
    CMD_ATOMIC  = 3'b010,
    CMD_FENCE   = 3'b011,
    CMD_INVALID = 3'b111
  } xbar_cmd_e;

  typedef struct packed {
    logic [ID_WIDTH-1:0]   id;
    logic [ADDR_WIDTH-1:0] addr;
    logic [DATA_WIDTH-1:0] data;
    xbar_cmd_e             cmd;
    logic                  last;
  } xbar_req_t;

  typedef struct packed {
    logic [ID_WIDTH-1:0]   id;
    logic [DATA_WIDTH-1:0] data;
    logic [1:0]            resp;
    logic                  last;
  } xbar_resp_t;

  function automatic int calc_sel_width(int n);
    if (n <= 1) return 1;
    return $clog2(n);
  endfunction

endpackage
