// Synchronous FIFO — pointer and flag control logic

module fifo_ctrl
  import fifo_pkg::*;
(
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic                  wr_en,
  input  logic                  rd_en,
  output logic [PTR_WIDTH-1:0]  wr_addr,
  output logic [PTR_WIDTH-1:0]  rd_addr,
  output logic                  full,
  output logic                  empty,
  output logic                  almost_full,
  output logic                  almost_empty
);

  ptr_t wr_ptr, rd_ptr;

  assign wr_addr = wr_ptr[PTR_WIDTH-1:0];
  assign rd_addr = rd_ptr[PTR_WIDTH-1:0];

  assign full  = (wr_ptr[PTR_WIDTH] != rd_ptr[PTR_WIDTH]) &&
                 (wr_ptr[PTR_WIDTH-1:0] == rd_ptr[PTR_WIDTH-1:0]);
  assign empty = (wr_ptr == rd_ptr);

  wire [PTR_WIDTH:0] count = rd_ptr - wr_ptr;
  assign almost_full  = (count >= AFULL_THR);
  assign almost_empty = (count <= AEMPTY_THRESH) && !empty;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr <= '0;
      rd_ptr <= '0;
    end else begin
      if (wr_en)
        wr_ptr <= wr_ptr + 1'b1;
      if (rd_en && !empty)
        rd_ptr <= rd_ptr + 1'b1;
    end
  end

endmodule
