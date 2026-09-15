A Flux Framework HPC cluster configuration at `/app/broken-config/config.toml` defines an 8-node simulated cluster (`node[0-7]`, 4 cores each) with three scheduling queues intended for workload isolation:

- **debug** (nodes 0–1): quick-turnaround jobs, max duration 30 minutes
- **batch** (nodes 2–5): production workloads, max duration 8 hours
- **gpu** (nodes 6–7, 2 GPUs each): GPU workloads, max duration 4 hours

The default queue for jobs submitted without an explicit `-q` flag must be `batch`.

The configuration contains multiple interacting bugs that cause resource property leakage across queue boundaries, prevent an entire queue from ever scheduling jobs, incorrectly exclude a node from the resource pool, and misroute default job submissions. Diagnose all issues and produce a corrected Flux TOML configuration at `/app/fixed-config/config.toml` that satisfies all the requirements above.

Each queue's jobs must run exclusively on their designated node group via resource properties and queue `requires` constraints. All 8 nodes must be available for scheduling (no exclusions). Queues must operate independently — disabling one must not affect job submission to others.

Consult the Flux configuration man pages (`flux-config-resource(5)`, `flux-config-queues(5)`, `flux-config-job-manager(5)`) and examine how `[[resource.config]]` entries assign properties to hosts, how `[queues.<name>]` sections define requires constraints, and how `[policy.jobspec.defaults.system]` sets the default queue.