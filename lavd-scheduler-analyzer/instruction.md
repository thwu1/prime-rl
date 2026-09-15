A gaming workload on a 12-core heterogeneous ARM big.LITTLE SoC is failing to sustain its 60fps frame rate target. The system's CPU topology, kernel scheduling trace, current CPU affinity configuration, and performance targets are in `/app/data/`.

Diagnose the scheduling bottleneck and produce a corrected CPU affinity configuration that simultaneously meets the frame time and energy targets.

## Data

- `/app/data/sysfs/` — per-CPU directory tree mirroring `/sys/devices/system/cpu/` (topology, power, cache, and frequency information for each CPU)
- `/app/data/trace.txt` — kernel ftrace scheduling events captured during 20 frames of the workload
- `/app/data/affinity.json` — current task-name to CPU-range assignments
- `/app/data/requirements.json` — frame time target (microseconds) and energy budget (joules)

## Deliverables (write to `/app/output/`)

**`topology.json`** — `{"cpus": {"<cpu_id>": {"capacity": <int>, "type": "<string>", "power_mw": <int>}, ...}}`

**`task_analysis.json`** — `{"tasks": {"<name>": {"pid": <int>, "avg_runtime_us": <float>, "depends_on": [<name>,...], "depended_by": [<name>,...]}, ...}}`

**`diagnosis.json`** — `{"current_frame_time_us": <float>, "target_frame_time_us": <float>, "current_energy_joules": <float>, "energy_budget_joules": <float>, "frame_time_met": <bool>, "energy_met": <bool>}`

**`affinity.json`** — `{"assignments": {"<task_name>": "<cpu_list>", ...}}` — corrected assignments meeting both targets

**`metrics.json`** — `{"projected_frame_time_us": <float>, "projected_energy_joules": <float>, "frame_time_met": <bool>, "energy_met": <bool>}`