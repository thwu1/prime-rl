module gpio_bank
#(
  parameter int NUM_PINS        = 8,
  parameter int DEBOUNCE_CYCLES = 4
)(
  input  logic                          clk,
  input  logic                          rst_n,
  input  logic [NUM_PINS-1:0]           pin_in,
  output logic [NUM_PINS-1:0]           pin_out,
  output logic [NUM_PINS-1:0]           pin_oe,
  input  logic [NUM_PINS-1:0]           out_data,
  input  logic [NUM_PINS-1:0]           out_enable,
  input  logic [$clog2(NUM_PINS)-1:0]   sel,
  output logic                          irq
);

  logic [NUM_PINS-1:0] debounced;
  logic [NUM_PINS-1:0] prev_debounced;
  logic [NUM_PINS-1:0] edge_detect;

  genvar gi;
  generate
    for (gi = 0; gi < NUM_PINS; gi++) begin : gen_pin
      logic [$clog2(DEBOUNCE_CYCLES):0] cnt;
      logic synced;

      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
          cnt <= '0;
          synced <= 1'b0;
          debounced[gi] <= 1'b0;
        end else begin
          if (pin_in[gi] != debounced[gi]) begin
            if (cnt >= DEBOUNCE_CYCLES - 1) begin
              debounced[gi] <= pin_in[gi];
              cnt <= '0;
            end else begin
              cnt <= cnt + 1'b1;
            end
          end else begin
            cnt <= '0;
          end
          synced <= pin_in[gi];
        end
      end
    end
  endgenerate

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      prev_debounced <= '0;
    else
      prev_debounced <= debounced;
  end

  assign edge_detect = debounced & ~prev_debounced;
  assign irq = |edge_detect;
  assign pin_out = out_data;
  assign pin_oe = out_enable;

endmodule
