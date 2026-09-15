An N×N grid contains hidden polyomino-shaped oil fields. You can probe the grid through two operations: exact single-cell drilling (cost 1) and cheaper but noisy aggregate queries over cell groups (cost 1/sqrt(k) for k cells). Your objective is to identify all oil-bearing cells on every provided instance while keeping the average sensing cost low.

The full problem specification — including the interactive judge protocol, noise model, required deliverables, interface definitions, and database schema — is in `/app/PROBLEM.md`. The environment also provides `/app/judge.py` (interactive evaluator), `/app/generate.py` (instance generator), `/app/scoring.h` (C interface to implement), and 5 test instances in `/app/instances/`.

**Success criteria:**
- All deliverables specified in `/app/PROBLEM.md` are implemented and functional
- The solver correctly identifies every oil cell on all 5 static instances and on dynamically generated instances
- Average normalized cost (total_cost / N²) across the 5 instances is at most 0.45
- `/app/results.db` is populated with per-instance outcomes matching the schema in `PROBLEM.md`