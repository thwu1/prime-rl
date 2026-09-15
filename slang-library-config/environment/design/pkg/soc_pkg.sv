package soc_pkg;

  parameter int DWIDTH = 32;
  parameter int AWIDTH = 16;
  parameter int NREGS  = 16;

  typedef enum logic [2:0] {
    ALU_ADD = 3'd0,
    ALU_SUB = 3'd1,
    ALU_AND = 3'd2,
    ALU_OR  = 3'd3,
    ALU_XOR = 3'd4,
    ALU_SLL = 3'd5,
    ALU_SRL = 3'd6,
    ALU_NOP = 3'd7
  } alu_op_e;

  typedef struct packed {
    logic [AWIDTH-1:0] addr;
    logic [DWIDTH-1:0] data;
    logic              wen;
    logic              ren;
  } bus_req_t;

  typedef struct packed {
    logic [DWIDTH-1:0] data;
    logic              valid;
    logic              error;
  } bus_resp_t;

endpackage
