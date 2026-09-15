module sync_fifo #(
  parameter DEPTH = 8,
  parameter WIDTH = 32
)(
  input              clk,
  input              rst_n,
  input              wr_en,
  input              rd_en,
  input  [WIDTH-1:0] wr_data,
  output [WIDTH-1:0] rd_data,
  output             full,
  output             empty,
  output [$clog2(DEPTH):0] count
);

  reg [WIDTH-1:0] mem [0:DEPTH-1];
  reg [$clog2(DEPTH):0] wr_ptr;
  reg [$clog2(DEPTH):0] rd_ptr;

  assign count   = wr_ptr - rd_ptr;
  assign full    = (count == DEPTH);
  assign empty   = (count == 0);
  assign rd_data = mem[rd_ptr[$clog2(DEPTH)-1:0]];

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr <= 0;
      rd_ptr <= 0;
    end else begin
      if (wr_en && !full) begin
        mem[wr_ptr[$clog2(DEPTH)-1:0]] <= wr_data;
        wr_ptr <= wr_ptr + 1;
      end
      if (rd_en && !empty)
        rd_ptr <= rd_ptr + 1;
    end
  end

endmodule
