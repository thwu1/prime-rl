A SAT-based dependency resolver at `/app/resolve.py` resolves package dependencies declared in manifest files against a registry at `/app/registry.json`. Constraint syntax is documented in `/app/FORMAT.md`. Five manifests with different dependency topologies are in `/app/manifests/`.

The resolver has multiple correctness and performance failures:

- `constrained.json` resolves to a lockfile that violates the version constraint semantics documented in `/app/FORMAT.md`.
- Several manifests may produce lockfiles with incorrect or suboptimal version selections due to structural deficiencies in the SAT formula construction.
- `deep.json` (large transitive dependency graph) fails to resolve within 30 seconds.
- `conflict.json` (intentionally unsatisfiable) produces only a generic one-line error with no diagnostic value.

Diagnose all root causes and fix the resolver so that it satisfies these requirements:

- `python3 /app/resolve.py <manifest>` prints a valid JSON lockfile (package name to version string, sorted keys) to stdout and exits 0 for satisfiable manifests. When multiple valid resolutions exist, prefer the latest compatible version of each package.
- `python3 /app/resolve.py <manifest>` prints structured multi-line conflict diagnostics to stderr and exits 1 for unsatisfiable manifests. Diagnostics must identify which packages have irreconcilable version requirements, name the dependency sources imposing those requirements, and include version constraint details.
- `python3 /app/resolve.py --dimacs <manifest>` exports the constraint formulation in DIMACS CNF format to stdout with `c var N pkg@ver` comment lines mapping variables to package-version pairs. Exit 0 regardless of satisfiability.

MiniSat is installed at `/usr/bin/minisat`. For every manifest, MiniSat's SAT/UNSAT verdict on the resolver's DIMACS output must agree with the resolver's own resolution outcome.