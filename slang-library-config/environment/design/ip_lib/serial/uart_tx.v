module uart_tx #(
  parameter CLKS_PER_BIT = 434
)(
  input            clk,
  input            rst_n,
  input  [7:0]     tx_byte,
  input            tx_start,
  output           tx_done,
  output           tx_active,
  output reg       tx_serial
);

  localparam IDLE  = 3'd0;
  localparam START = 3'd1;
  localparam DATA  = 3'd2;
  localparam STOP  = 3'd3;
  localparam DONE  = 3'd4;

  reg [2:0]  state;
  reg [$clog2(CLKS_PER_BIT)-1:0] clk_cnt;
  reg [2:0]  bit_idx;
  reg [7:0]  shift_reg;
  reg        r_done;
  reg        r_active;

  assign tx_done   = r_done;
  assign tx_active = r_active;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state     <= IDLE;
      tx_serial <= 1'b1;
      clk_cnt   <= 0;
      bit_idx   <= 0;
      r_done    <= 1'b0;
      r_active  <= 1'b0;
    end else begin
      case (state)
        IDLE: begin
          tx_serial <= 1'b1;
          r_done    <= 1'b0;
          r_active  <= 1'b0;
          if (tx_start) begin
            shift_reg <= tx_byte;
            state     <= START;
            r_active  <= 1'b1;
          end
        end
        START: begin
          tx_serial <= 1'b0;
          if (clk_cnt < CLKS_PER_BIT - 1) begin
            clk_cnt <= clk_cnt + 1;
          end else begin
            clk_cnt <= 0;
            state   <= DATA;
            bit_idx <= 0;
          end
        end
        DATA: begin
          tx_serial <= shift_reg[bit_idx];
          if (clk_cnt < CLKS_PER_BIT - 1) begin
            clk_cnt <= clk_cnt + 1;
          end else begin
            clk_cnt <= 0;
            if (bit_idx == 7)
              state <= STOP;
            else
              bit_idx <= bit_idx + 1;
          end
        end
        STOP: begin
          tx_serial <= 1'b1;
          if (clk_cnt < CLKS_PER_BIT - 1) begin
            clk_cnt <= clk_cnt + 1;
          end else begin
            clk_cnt <= 0;
            r_done  <= 1'b1;
            state   <= DONE;
          end
        end
        DONE: begin
          r_done   <= 1'b0;
          r_active <= 1'b0;
          state    <= IDLE;
        end
        default: state <= IDLE;
      endcase
    end
  end

endmodule
