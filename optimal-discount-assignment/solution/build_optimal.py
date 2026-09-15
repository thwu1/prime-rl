#!/usr/bin/env python3
"""
Reads the base pricing_engine.py from /opt/pricing_task/ and the optimal
solver from /solution/optimal_impl.py, then writes a combined module to
/app/pricing_engine.py with calculate_optimal_total replaced by the
DP-based optimizer.
"""

# Read the base pricing engine (from Docker image, not /app/)
with open("/opt/pricing_task/pricing_engine.py") as f:
    engine_code = f.read()

# Read the optimal solver implementation
with open("/solution/optimal_impl.py") as f:
    solver_code = f.read()

# Extract solver function code (skip canary and module-level docstring/imports)
lines = solver_code.split("\n")
code_lines = []
past_canary = False
for line in lines:
        past_canary = True
        continue
    if past_canary:
        code_lines.append(line)

helper_code = "\n".join(code_lines)

# Find the calculate_optimal_total function in the base module
marker = "def calculate_optimal_total("
idx = engine_code.find(marker)
if idx == -1:
    raise RuntimeError("Could not find calculate_optimal_total in pricing_engine.py")

# Keep everything before calculate_optimal_total (docstring, imports, load funcs, greedy)
prefix = engine_code[:idx]

# Combine: base prefix + lru_cache import + optimal solver functions
new_code = prefix.rstrip() + "\n\n"
new_code += "from functools import lru_cache\n\n"
new_code += helper_code.strip() + "\n"

with open("/app/pricing_engine.py", "w") as f:
    f.write(new_code)

print("Optimal solver installed successfully.")
