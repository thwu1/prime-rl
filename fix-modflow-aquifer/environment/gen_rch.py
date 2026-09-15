#!/usr/bin/env python3
"""Generate list-based RCH file for TWRI model (15x15 grid, uniform recharge)."""
with open('/app/model/ex-gwf-twri01.rch', 'w') as f:
    f.write("BEGIN OPTIONS\nEND OPTIONS\n\n")
    f.write("BEGIN DIMENSIONS\n  MAXBOUND  225\nEND DIMENSIONS\n\n")
    f.write("BEGIN PERIOD 1\n")
    for i in range(1, 16):
        for j in range(1, 16):
            f.write(f"  1  {i}  {j}  3.00000000e-08\n")
    f.write("END PERIOD 1\n")
