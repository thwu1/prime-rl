Bipartite graph instances in `/app/instances/` are in the PACE Challenge `.gr` format. Each encodes a graph G = ((A ∪ B), E) where partition A has a fixed linear order (vertices 1..n₀) and partition B (vertices n₀+1..n₀+n₁) must be ordered to minimize edge crossings.

**Input format** — first non-comment line: `p ocr <n0> <n1> <m>`, then `m` edge lines `<a> <b>`. Comment lines start with `c`.

**Crossing definition** — edges (a₁, b₁) and (a₂, b₂) cross when a₁ < a₂ and pos(b₁) > pos(b₂), or vice versa.

Build a solver pipeline at `/app/solver` that computes provably optimal B-orderings using **two independent methods** that must agree:

**SAT-based method** — Encode the OSCM decision problem ("does an ordering with ≤ k crossings exist?") as propositional satisfiability. Generate DIMACS CNF files and solve them with `minisat` (installed at `/usr/bin/minisat`). The CNF must encode Boolean ordering variables with transitivity axioms, crossing indicator literals, and a cardinality constraint (e.g., sequential counter) bounding the number of crossings.

**ILP-based method** — Formulate OSCM as an integer linear program. Generate model files in CPLEX LP format and solve them with `glpsol` (installed at `/usr/bin/glpsol`) to integer optimality. The ILP must use binary ordering and crossing indicator variables with transitivity inequalities and crossing-linking constraints.

### Required outputs

- `/app/output/instance_XX.sol` — Optimal B-ordering (one vertex ID per line, n₁ lines)
- `/app/sat/instance_XX.cnf` — DIMACS CNF encoding for the optimal crossing bound (must be satisfiable by minisat)
- `/app/ilp/instance_XX.lp` — GLPK LP-format integer program (must solve to optimality via glpsol with correct objective)
- `/app/report.json` — `{"instance_01": {"sat_crossings": N, "ilp_crossings": N}, ...}` confirming both methods yield identical optimal crossing counts

All 7 instances must be solved. Sizes range from n₁=3 to n₁=12.