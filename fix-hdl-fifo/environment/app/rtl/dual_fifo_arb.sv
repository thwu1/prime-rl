// Dual-channel FIFO arbiter — top-level integration

module dual_fifo_arb
  import fifo_pkg::*;
(
  input  logic    clk,
  input  logic    rst_n,
  // Channel A write interface
  input  logic    ch_a_wr_en,
  input  data_t   ch_a_din,
  output logic    ch_a_full,
  output logic    ch_a_almost_full,
  // Channel B write interface
  input  logic    ch_b_wr_en,
  input  data_t   ch_b_din,
  output logic    ch_b_full,
  output logic    ch_b_almost_full,
  // Arbitrated output (valid/ready handshake)
  output data_t   out_data,
  output logic    out_valid,
  input  logic    out_ready
);

  // Internal signals — Channel A FIFO
  data_t  fifo_a_dout;
  logic   fifo_a_empty, fifo_a_almost_empty;
  logic   fifo_a_rd_en;

  // Internal signals — Channel B FIFO
  data_t  fifo_b_dout;
  logic   fifo_b_empty, fifo_b_almost_empty;
  logic   fifo_b_rd_en;

  // Channel A FIFO instance
  fifo u_fifo_a (
    .clk          (clk),
    .rst_n        (rst_n),
    .wr_en        (ch_a_wr_en),
    .rd_en        (fifo_a_rd_en),
    .din          (ch_a_din),
    .dout         (fifo_a_dout),
    .full         (ch_a_full),
    .empty        (fifo_a_empty),
    .almost_full  (ch_a_almost_full),
    .almost_empty (fifo_a_almost_empty)
  );

  // Channel B FIFO instance
  fifo u_fifo_b (
    .clk          (clk),
    .rst_n        (rst_n),
    .wr_en        (ch_b_wr_en),
    .rd_en        (fifo_b_rd_en),
    .din          (ch_b_din),
    .dout         (fifo_b_dout),
    .full         (ch_b_full),
    .empty        (fifo_b_empty),
    .almost_full  (ch_b_almost_full),
    .almost_empty (fifo_b_almost_empty)
  );

  // Round-robin arbiter — channel A has initial priority after reset
  arbiter u_arb (
    .clk        (clk),
    .rst_n      (rst_n),
    .ch_a_data  (fifo_a_dout),
    .ch_a_valid (!fifo_a_empty),
    .ch_a_ready (fifo_a_rd_en),
    .ch_b_data  (fifo_b_dout),
    .ch_b_valid (!fifo_b_empty),
    .ch_b_ready (fifo_b_rd_en),
    .out_data   (out_data),
    .out_valid  (out_valid),
    .out_ready  (out_ready)
  );

endmodule
