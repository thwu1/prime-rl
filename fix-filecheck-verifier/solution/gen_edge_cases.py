#!/usr/bin/env python3
"""Generate edge case test files in /app/edge_cases/."""
import os

edge_dir = "/app/edge_cases"
os.makedirs(edge_dir, exist_ok=True)

# Edge case 1: CHECK-COUNT with variable capture across consecutive lines
with open(f"{edge_dir}/count_with_vars.check", "w") as f:
    f.write("; CHECK-COUNT-2: reg[[N:[0-9]+]] = load i32\n")
with open(f"{edge_dir}/count_with_vars.input", "w") as f:
    f.write("reg5 = load i32\nreg5 = load i32\n")

# Edge case 2: CHECK-DAG group followed by CHECK-NOT
with open(f"{edge_dir}/dag_then_not.check", "w") as f:
    f.write("; CHECK: header\n")
    f.write("; CHECK-DAG: bravo\n")
    f.write("; CHECK-DAG: alpha\n")
    f.write("; CHECK-NOT: error\n")
    f.write("; CHECK: footer\n")
with open(f"{edge_dir}/dag_then_not.input", "w") as f:
    f.write("header\nalpha\nbravo\ninfo: ok\nfooter\n")

# Edge case 3: Multiple CHECK-NOT between CHECK-LABEL sections
with open(f"{edge_dir}/label_not_sections.check", "w") as f:
    f.write("; CHECK-LABEL: func_a\n")
    f.write("; CHECK-NOT: unreachable\n")
    f.write("; CHECK: ret\n")
    f.write("; CHECK-LABEL: func_b\n")
    f.write("; CHECK-NOT: unreachable\n")
    f.write("; CHECK: ret\n")
with open(f"{edge_dir}/label_not_sections.input", "w") as f:
    f.write("func_a:\n  add r0, r1\n  ret\nfunc_b:\n  sub r0, r1\n  ret\n")

# Edge case 4: CHECK-SAME after CHECK-DAG
with open(f"{edge_dir}/dag_same.check", "w") as f:
    f.write("; CHECK-DAG: x = 10, y = 20\n")
    f.write("; CHECK-DAG: a = 30, b = 40\n")
with open(f"{edge_dir}/dag_same.input", "w") as f:
    f.write("a = 30, b = 40\nx = 10, y = 20\n")

print(f"Created 4 edge case test pairs in {edge_dir}")
