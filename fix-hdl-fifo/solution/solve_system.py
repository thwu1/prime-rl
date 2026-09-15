#!/usr/bin/env python3
"""
Fix all 6 FIFO bugs and create the missing arbiter module.
Also ensures the top-level integration module exists.

FIFO Bugs:
  A (fifo_mem.sv):   Missing 'import fifo_pkg::*;' — types/parameters undefined
  B (fifo_ctrl.sv):  Typo 'AFULL_THR' should be 'AFULL_THRESH'
  C (fifo.sv):       Port name '.write_en' should be '.wr_en' on fifo_mem instance
  D (fifo.sv):       Port name '.rd_pointer' should be '.rd_addr' on fifo_ctrl instance
  E (fifo_ctrl.sv):  Write pointer increments without !full guard
  F (fifo_ctrl.sv):  Fill count uses 'rd_ptr - wr_ptr' instead of 'wr_ptr - rd_ptr'

Arbiter:
  Create /app/rtl/arbiter.sv — round-robin arbiter with valid/ready handshaking,
  combinational data path, and backpressure support.
"""

import os

os.makedirs('/app/rtl', exist_ok=True)


def fix_file(path, replacements):
    """Read file, apply all (old, new) replacements, write back."""
    with open(path, 'r') as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)


# Bug A: fifo_mem.sv — add missing package import
fix_file('/app/rtl/fifo_mem.sv', [
    (
        'module fifo_mem\n#(',
        'module fifo_mem\n  import fifo_pkg::*;\n#(',
    ),
])

# Bugs B, F, E: fifo_ctrl.sv
fix_file('/app/rtl/fifo_ctrl.sv', [
    # Bug B: wrong parameter name
    ('AFULL_THR)', 'AFULL_THRESH)'),
    # Bug F: reversed subtraction in fill-level count
    ('rd_ptr - wr_ptr', 'wr_ptr - rd_ptr'),
    # Bug E: missing overflow guard
    (
        'if (wr_en)\n        wr_ptr',
        'if (wr_en && !full)\n        wr_ptr',
    ),
])

# Bugs C, D: fifo.sv — fix port name mismatches
fix_file('/app/rtl/fifo.sv', [
    # Bug C: fifo_mem port name
    ('.write_en(', '.wr_en   ('),
    # Bug D: fifo_ctrl port name
    ('.rd_pointer   (', '.rd_addr      ('),
])

# Ensure top-level integration module exists at /app/rtl/dual_fifo_arb.sv
DUAL_FIFO_ARB_SV = """\
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
"""

if not os.path.isfile('/app/rtl/dual_fifo_arb.sv'):
    with open('/app/rtl/dual_fifo_arb.sv', 'w') as f:
        f.write(DUAL_FIFO_ARB_SV)
    print("Created missing dual_fifo_arb.sv.")

# Create the arbiter module
ARBITER_SV = """\
// Round-robin arbiter for dual-channel FIFO system

module arbiter
  import fifo_pkg::*;
(
  input  logic    clk,
  input  logic    rst_n,
  // Channel A
  input  data_t   ch_a_data,
  input  logic    ch_a_valid,
  output logic    ch_a_ready,
  // Channel B
  input  data_t   ch_b_data,
  input  logic    ch_b_valid,
  output logic    ch_b_ready,
  // Arbitrated output
  output data_t   out_data,
  output logic    out_valid,
  input  logic    out_ready
);

  // Turn register: 0 = channel A priority, 1 = channel B priority
  logic turn;

  // Arbitration decision
  logic select_a, select_b;

  // Round-robin selection with fallthrough to available channel
  always_comb begin
    select_a = 1'b0;
    select_b = 1'b0;
    if (!turn) begin
      // Channel A has priority
      if (ch_a_valid)      select_a = 1'b1;
      else if (ch_b_valid) select_b = 1'b1;
    end else begin
      // Channel B has priority
      if (ch_b_valid)      select_b = 1'b1;
      else if (ch_a_valid) select_a = 1'b1;
    end
  end

  // Output mux — combinational data path
  assign out_data  = select_a ? ch_a_data : ch_b_data;
  assign out_valid = select_a | select_b;

  // Backpressure: only consume input when output is accepted
  assign ch_a_ready = select_a & out_ready;
  assign ch_b_ready = select_b & out_ready;

  // Toggle turn when the prioritized channel is served
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      turn <= 1'b0;
    else if (out_valid && out_ready) begin
      if (select_a && !turn)
        turn <= 1'b1;
      else if (select_b && turn)
        turn <= 1'b0;
    end
  end

endmodule
"""

with open('/app/rtl/arbiter.sv', 'w') as f:
    f.write(ARBITER_SV)

print("All FIFO bugs fixed and arbiter module created.")
