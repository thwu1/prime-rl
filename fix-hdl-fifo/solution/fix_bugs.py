#!/usr/bin/env python3
"""
Fix all 6 bugs in the FIFO RTL design.

Bug A (fifo_mem.sv):   Missing 'import fifo_pkg::*;' — types and parameters undefined
Bug B (fifo_ctrl.sv):  Typo 'AFULL_THR' should be 'AFULL_THRESH'
Bug C (fifo.sv):       Port name '.write_en' should be '.wr_en' on fifo_mem instance
Bug D (fifo.sv):       Port name '.rd_pointer' should be '.rd_addr' on fifo_ctrl instance
Bug E (fifo_ctrl.sv):  Write pointer increments without !full guard — allows writes past capacity
Bug F (fifo_ctrl.sv):  Fill count uses 'rd_ptr - wr_ptr' instead of 'wr_ptr - rd_ptr'
"""

import re


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

# Bugs B, E, F: fifo_ctrl.sv — fix parameter name, add full guard, fix count direction
fix_file('/app/rtl/fifo_ctrl.sv', [
    # Bug B: wrong parameter name
    ('AFULL_THR)', 'AFULL_THRESH)'),
    # Bug F: reversed subtraction in fill-level count
    ('rd_ptr - wr_ptr', 'wr_ptr - rd_ptr'),
    # Bug E: missing overflow guard — must check !full before incrementing write pointer
    (
        'if (wr_en)\n        wr_ptr',
        'if (wr_en && !full)\n        wr_ptr',
    ),
])

# Bugs C, D: fifo.sv — fix port name mismatches in module instantiations
fix_file('/app/rtl/fifo.sv', [
    # Bug C: fifo_mem port name
    ('.write_en(', '.wr_en   ('),
    # Bug D: fifo_ctrl port name
    ('.rd_pointer   (', '.rd_addr      ('),
])

print("All 6 bugs fixed successfully.")
