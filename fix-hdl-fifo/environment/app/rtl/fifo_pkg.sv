// Synchronous FIFO — shared package definitions

package fifo_pkg;
  parameter int FIFO_DEPTH      = 16;
  parameter int DATA_WIDTH      = 8;
  parameter int PTR_WIDTH       = $clog2(FIFO_DEPTH);
  parameter int AFULL_THRESH    = FIFO_DEPTH - 2;
  parameter int AEMPTY_THRESH   = 2;

  typedef logic [DATA_WIDTH-1:0] data_t;
  typedef logic [PTR_WIDTH:0]    ptr_t;   // extra MSB for wrap-around detection
endpackage
