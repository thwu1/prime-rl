A SIMP topology optimization code at `/app/` computes the minimum-compliance material layout for a 2D cantilever beam (left edge clamped, unit downward point load at the bottom-right corner, volume fraction target in `/app/config.json`).

The driver `/app/run_optimization.py` and `/app/config.json` are correct. The file `/app/framework.py` contains multiple numerical defects that cause the optimizer to produce physically incorrect results — the code runs without errors but the output design is wrong.

Diagnose and fix all bugs in `/app/framework.py` so that `python3 /app/run_optimization.py` produces:

- Monotonically decreasing compliance converging within the configured iteration limit
- Final volume fraction within 2% of the configured target (0.5)
- A density field with distinct solid (>0.9) and void (<0.1) regions forming a plausible load-bearing structure from the clamped edge to the loaded corner