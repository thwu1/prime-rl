A GPU performance team has analyzed a CUDA warptiling SGEMM kernel and recommended configurations for three GPU architectures. Their analysis contains errors — some subtle, some fundamental. Your job is to audit their work.

The kernel source is at `/app/kernel_warptiling.cuh` with launch constraints at `/app/runner_constraints.cu`. GPU architecture specifications are in a SQLite database at `/app/gpu_specs.db`. Valid parameter ranges are in `/app/param_ranges.csv`. The team's analysis is at `/app/team_analysis.json`. The output schema is defined in `/app/problem_spec.json`.

Audit every team-recommended configuration: determine whether each is actually valid for the kernel (checking both explicit `static_assert` constraints from the runner and implicit constraints arising from the kernel's vectorized memory access patterns), compute the correct theoretical occupancy and identify the limiting hardware resource on each GPU architecture, and flag every discrepancy with the team's claims.

Evaluate whether the team's "best pick" for each GPU is truly optimal by enumerating the full valid parameter space and finding the actual highest-occupancy configuration. Compute the Pareto-optimal configuration count across all three architectures, and a portability score for each valid team config.

Produce `/app/audit_results.json` conforming to the schema in `/app/problem_spec.json`.