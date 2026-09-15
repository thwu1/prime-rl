The n-Queens Completion problem asks whether pre-placed non-attacking queens on an n×n board can be extended to a full set of n non-attacking queens. This problem is NP-Complete (Gent et al., JAIR 2017), and its counting variant is #P-Complete.

Fifteen instances in `/app/instances/` require three capabilities:

**Decision and solution recovery**: Determine whether each instance is satisfiable or unsatisfiable. For satisfiable instances, produce one valid completion.

**Exact solution counting**: Instances with `"count_solutions": true` require the exact number of distinct valid completions — finding one solution is insufficient.

**Minimal unsatisfiable core extraction**: For each unsatisfiable instance, identify a minimal subset of the pre-placed queens that already causes unsatisfiability on its own. "Minimal" means removing any single queen from the reported core must render the instance satisfiable again.

Write all results to `/app/results.json`. See `/app/README.txt` for the input/output format.

Board sizes range from 5 to 100. All 15 instances must be solved within the time limit.