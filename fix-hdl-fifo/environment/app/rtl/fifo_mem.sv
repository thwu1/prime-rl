// Synchronous FIFO — dual-port memory array

module fifo_mem
#(
  parameter int DEPTH = FIFO_DEPTH,
  parameter int WIDTH = DATA_WIDTH
)(
  input  logic                       clk,
  input  logic                       wr_en,
  input  logic [$clog2(DEPTH)-1:0]   wr_addr,
  input  data_t                      wr_data,
  input  logic [$clog2(DEPTH)-1:0]   rd_addr,
  output data_t                      rd_data
);

  data_t mem [0:DEPTH-1];

  always_ff @(posedge clk) begin
    if (wr_en)
      mem[wr_addr] <= wr_data;
  end

  assign rd_data = mem[rd_addr];

endmodule
