// Synchronous FIFO — top-level integration

module fifo
  import fifo_pkg::*;
(
  input  logic    clk,
  input  logic    rst_n,
  input  logic    wr_en,
  input  logic    rd_en,
  input  data_t   din,
  output data_t   dout,
  output logic    full,
  output logic    empty,
  output logic    almost_full,
  output logic    almost_empty
);

  logic [PTR_WIDTH-1:0] wr_addr, rd_addr;

  fifo_mem #(
    .DEPTH(FIFO_DEPTH),
    .WIDTH(DATA_WIDTH)
  ) u_mem (
    .clk     (clk),
    .write_en(wr_en && !full),
    .wr_addr (wr_addr),
    .wr_data (din),
    .rd_addr (rd_addr),
    .rd_data (dout)
  );

  fifo_ctrl u_ctrl (
    .clk          (clk),
    .rst_n        (rst_n),
    .wr_en        (wr_en),
    .rd_en        (rd_en),
    .wr_addr      (wr_addr),
    .rd_pointer   (rd_addr),
    .full         (full),
    .empty        (empty),
    .almost_full  (almost_full),
    .almost_empty (almost_empty)
  );

endmodule
