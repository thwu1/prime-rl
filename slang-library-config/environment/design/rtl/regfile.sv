module regfile
  import soc_pkg::*;
#(
  parameter int NUM_REGS = NREGS,
  parameter int DATA_W   = DWIDTH
)(
  input  logic                         clk,
  input  logic                         rst_n,
  input  logic [$clog2(NUM_REGS)-1:0]  rs1_addr,
  input  logic [$clog2(NUM_REGS)-1:0]  rs2_addr,
  input  logic [$clog2(NUM_REGS)-1:0]  wd_addr,
  input  logic [DATA_W-1:0]            wd_data,
  input  logic                         wd_en,
  output logic [DATA_W-1:0]            rs1_data,
  output logic [DATA_W-1:0]            rs2_data
);

  logic [DATA_W-1:0] mem [NUM_REGS];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < NUM_REGS; i++)
        mem[i] <= '0;
    end else if (wd_en && wd_addr != '0) begin
      mem[wd_addr] <= wd_data;
    end
  end

  assign rs1_data = (rs1_addr == '0) ? '0 : mem[rs1_addr];
  assign rs2_data = (rs2_addr == '0) ? '0 : mem[rs2_addr];

endmodule
