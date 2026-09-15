A production HTTP service `portal-api` experienced a latency regression after deploying v2.14.0. CPU profiles were captured using Linux `perf` during steady-state production traffic before and after the deployment. The two captures were made under different load levels.

Service metadata is at `/app/metadata.json`. Raw CPU profile data is in `/app/profiles/`. The profile captures contain interleaved samples from all processes that were active on the host during each session.

Analyze the CPU profiles to identify the root causes of the regression. Produce `/app/diagnosis.json` containing:

- `target_pid` (int): PID of the service under investigation
- `baseline_cpu_samples` (int): total CPU samples attributed to the target process in the baseline capture
- `regression_cpu_samples` (int): total CPU samples attributed to the target process in the regression capture
- `new_functions` (list[str]): functions that appear at call-stack leaves exclusively in the regression profile, alphabetically sorted
- `removed_functions` (list[str]): functions that appear at call-stack leaves exclusively in the baseline profile, alphabetically sorted
- `top_regressions` (list[dict]): the 10 functions whose CPU consumption grew most disproportionately relative to the overall load increase, each as `{"function": str, "impact": float}`, sorted descending by impact
- `root_cause_groups` (dict[str, list[str]]): new leaf functions grouped by the topmost function in their regression call chain that does not appear as a non-leaf in any baseline stack; if no such ancestor exists the leaf maps to itself. Keys and values alphabetically sorted.