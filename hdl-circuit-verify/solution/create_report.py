#!/usr/bin/env python3
"""Create the analysis report comparing ripple-carry and optimized ALU designs."""


import sys
import json

sys.path.insert(0, '/app')
from hdl import Wire, Bus, const
from analysis import count_gates, critical_path, max_fanout

# Analyze original (fixed) ripple-carry ALU
Wire.reset()
from design import build_alu
opcode1 = Bus.input(3, "op1")
a1 = Bus.input(4, "a1")
b1 = Bus.input(4, "b1")
result1 = build_alu(opcode1, a1, b1)
orig_gates = count_gates(result1)
orig_depth = critical_path(result1)
orig_fanout = max_fanout(result1)

# Analyze optimized ALU
Wire.reset()
from fast_alu import build_alu_fast
opcode2 = Bus.input(3, "op2")
a2 = Bus.input(4, "a2")
b2 = Bus.input(4, "b2")
result2 = build_alu_fast(opcode2, a2, b2)
opt_gates = count_gates(result2)
opt_depth = critical_path(result2)
opt_fanout = max_fanout(result2)

report = {
    "bugs": [
        {
            "function": "full_adder",
            "location": "design.py: c2 = a & cin",
            "description": (
                "Carry term c2 uses raw input 'a' instead of intermediate "
                "XOR 's1 = a ^ b'. Correct carry-out is (a & b) | ((a ^ b) & cin). "
                "Using 'a & cin' drops carry when a=0, b=1, cin=1, corrupting "
                "ADD and SUB for many operand combinations."
            ),
            "fix": "Changed 'c2 = a & cin' to 'c2 = s1 & cin'"
        },
        {
            "function": "subtractor",
            "location": "design.py: ripple_adder(a, not_b, const(0))",
            "description": (
                "Two's complement subtraction requires a + ~b + 1, but the "
                "carry-in is const(0) instead of const(1). This computes "
                "a + ~b = a - b - 1 (mod 16), always off by one."
            ),
            "fix": "Changed const(0) to const(1) for the carry-in"
        },
        {
            "function": "shift_right",
            "location": "design.py: a[(i + 1) % n]",
            "description": (
                "Modular indexing '(i+1) % n' wraps bit 0 into the MSB "
                "position, implementing a right rotation instead of a "
                "logical right shift. Odd inputs gain a spurious high bit."
            ),
            "fix": "Changed to 'a[i+1] if i+1 < n else const(0)' for zero-fill"
        },
        {
            "function": "build_alu",
            "location": "design.py: mux(opcode[0], res_xor, res_not)",
            "description": (
                "The if_one/if_zero arguments for the XOR/NOT selector mux are "
                "swapped. mux returns if_one when sel=1, so opcode 100 (XOR, "
                "bit0=0) incorrectly selects res_not and vice versa."
            ),
            "fix": "Swapped to mux(opcode[0], res_not, res_xor)"
        }
    ],
    "analysis": {
        "original": {
            "gate_count": orig_gates,
            "critical_path_depth": orig_depth,
            "max_fanout": orig_fanout
        },
        "optimized": {
            "gate_count": opt_gates,
            "critical_path_depth": opt_depth,
            "max_fanout": opt_fanout
        }
    },
    "evaluation": (
        "The optimized adder computes all carry bits in parallel using "
        "generate and propagate signals, eliminating the sequential carry "
        "chain of the ripple-carry adder. This reduces the critical path "
        "depth at the cost of additional gates for the expanded carry "
        "equations. The optimized design also exhibits higher maximum fanout "
        "because early-stage generate and propagate signals fan out to "
        "multiple carry computation paths. For the 4-bit ALU, the optimized "
        "design's wider carry network trades gate count and wiring complexity "
        "for latency, which is the dominant optimization target in synchronous "
        "digital designs where clock frequency is limited by the longest "
        "combinational path."
    )
}

with open('/app/report.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"Report: original={orig_gates} gates, depth {orig_depth}, fanout {orig_fanout}; "
      f"optimized={opt_gates} gates, depth {opt_depth}, fanout {opt_fanout}")
