A production web service experienced severe performance degradation. An SRE captured raw system telemetry during the incident into `/app/incident/`. The `README.txt` in that directory describes the data layout, timing, and storage topology.

Investigate the incident and produce two artifacts:

1. `/app/flamegraph.svg` — A CPU flame graph visualization generated from the raw profiling data.

2. `/app/diagnosis.json` — A structured root-cause analysis containing:
   - `cpu_bottleneck_function` (string): The function that is the primary CPU bottleneck by self time
   - `cpu_bottleneck_percentage` (float, 2 decimal places): That function's share of total CPU samples
   - `pathological_pid` (int): PID of a process exhibiting a wasteful repetitive syscall pattern
   - `pathological_syscall_count` (int): How many times the wasteful syscall occurs in its trace
   - `memory_leak_pid` (int): PID whose resident memory grew the most over the observation window
   - `memory_growth_kb` (int): That process's total RSS change in kB
   - `disk_bottleneck_device` (string): The most saturated block device
   - `disk_queue_depth` (float, 2 decimal places): That device's average request queue depth
   - `network_error_interface` (string): Network interface that accumulated the most new errors
   - `network_error_count` (int): Total new errors on that interface over the observation window
   - `root_cause_pid` (int): PID of the process whose behavior triggered the cascade of degradation across subsystems
   - `causal_chain` (array of strings): Ordered sequence of causally linked subsystem failures, from root cause to final symptom. Choose from: `"memory_leak"`, `"disk_saturation"`, `"cpu_contention"`, `"network_errors"`, `"syscall_abuse"`. Include only failures that are causally connected; omit independent problems.