`include "soc_config.svh"

module soc_top
  import soc_pkg::*;
#(
  parameter int CLK_FREQ   = `DEFAULT_CLK_FREQ,
  parameter int BAUD_RATE  = `DEFAULT_BAUD_RATE,
  parameter int FIFO_DEPTH = `FIFO_DEPTH_CFG,
  parameter int GPIO_PINS  = 8,
  parameter int DEBOUNCE_W = 4
)(
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic [GPIO_PINS-1:0]  gpio_in,
  output logic [GPIO_PINS-1:0]  gpio_out,
  output logic                  uart_txd,
  output logic                  gpio_irq
);

  // CPU signals
  logic [DWIDTH-1:0] cpu_result;
  logic [2:0]        cpu_flags;

  // FIFO signals
  logic fifo_wr, fifo_rd, fifo_full, fifo_empty;
  logic [7:0] fifo_wdata, fifo_rdata;
  logic [$clog2(FIFO_DEPTH):0] fifo_count;

  // UART signals
  logic uart_start, uart_done, uart_active;

  // GPIO signals
  logic [GPIO_PINS-1:0] gpio_out_pins;
  logic [GPIO_PINS-1:0] gpio_oe;

  cpu_core #(
    .WIDTH (DWIDTH)
  ) u_cpu (
    .clk    (clk),
    .rst_n  (rst_n),
    .opcode (alu_op_e'(gpio_in[2:0])),
    .rs1    (gpio_in[7:4]),
    .rs2    (gpio_in[3:0]),
    .rd     (gpio_in[7:4]),
    .we     (gpio_in[3]),
    .result (cpu_result),
    .flags  (cpu_flags)
  );

  sync_fifo #(
    .DEPTH (FIFO_DEPTH),
    .WIDTH (8)
  ) u_fifo (
    .clk     (clk),
    .rst_n   (rst_n),
    .wr_en   (fifo_wr),
    .rd_en   (fifo_rd),
    .wr_data (fifo_wdata),
    .rd_data (fifo_rdata),
    .full    (fifo_full),
    .empty   (fifo_empty),
    .count   (fifo_count)
  );

  localparam int CLKS_PER_BIT = CLK_FREQ / BAUD_RATE;

  uart_tx #(
    .CLKS_PER_BIT (CLKS_PER_BIT)
  ) u_uart (
    .clk       (clk),
    .rst_n     (rst_n),
    .tx_byte   (fifo_rdata),
    .tx_start  (uart_start),
    .tx_done   (uart_done),
    .tx_active (uart_active),
    .tx_serial (uart_txd)
  );

  gpio_bank #(
    .NUM_PINS        (GPIO_PINS),
    .DEBOUNCE_CYCLES (DEBOUNCE_W)
  ) u_gpio (
    .clk        (clk),
    .rst_n      (rst_n),
    .pin_in     (gpio_in),
    .pin_out    (gpio_out_pins),
    .pin_oe     (gpio_oe),
    .out_data   (cpu_result[GPIO_PINS-1:0]),
    .out_enable ({GPIO_PINS{1'b1}}),
    .sel        ('0),
    .irq        (gpio_irq)
  );

  assign gpio_out = gpio_out_pins & gpio_oe;

  // Simple glue logic
  assign fifo_wdata = gpio_in[7:0];
  assign fifo_wr    = ~fifo_full & gpio_in[0];
  assign fifo_rd    = ~fifo_empty & ~uart_active & ~uart_start;
  assign uart_start = ~fifo_empty & ~uart_active;

endmodule
