Design an optimal heterogeneous 4-cluster processor chip. Each cluster contains 2 identical out-of-order cores sharing an L2 cache. The 8 workloads (`matmul`, `bfs`, `sort`, `queens`, `stream`, `crypto`, `fft`, `lzma`) must each be assigned to exactly one cluster, with exactly 2 workloads per cluster. Shared-cache interference degrades effective IPC for co-located workloads.

## Tools and Data

- `/app/bin/archsim` is an OoO processor simulator. Required flags: `--width`, `--rob-size`, `--int-regs` (must be > 32), `--fp-regs` (must be > 32), `--workload`. Add `--json` for JSON output. Use `--paired <workload2>` to simulate shared-L2 interference between two co-located workloads. In JSON mode, solo output includes `ipc`, `area`, `power_watts`; paired output includes `paired_ipc1`, `paired_ipc2`, `area`, `power_watts`.
- `/app/workloads.db` is a SQLite database with a `workloads` table (columns: `name`, `priority_weight`) and a pre-created `experiments` table (columns: `width`, `rob_size`, `num_int_regs`, `num_fp_regs`, `workload`, `paired_workload`, `ipc`, `area`, `power_watts`).
- `/app/chip_constraints.toml` defines chip layout and constraints.

## Constraints

Clusters are arranged in a 2x2 grid (IDs 0-3). Adjacent pairs: (0,1), (0,2), (1,3), (2,3).

- **Area budget**: total chip area (sum of `area_per_core * 2` across all 4 clusters) must not exceed 28000.
- **Power budget**: total power (sum of `power_per_core_watts * 2` across all 4 clusters) must not exceed 35.0 W.
- **Thermal adjacency**: a cluster is "hot" if its `area_per_core` exceeds 2500. No two adjacent clusters may both be hot.
- **IPC correctness**: all solo IPC and interference-adjusted IPC values reported in the output must match `archsim` output. Interference-adjusted IPC must be <= solo IPC.

## Objective

Maximize **weighted throughput**: the sum of `priority_weight(w) * interference_adjusted_ipc(w)` over all 8 workloads. The solution must achieve a weighted throughput of at least **30.0**.

## Required Outputs

### 1. Populate the `experiments` table in `/app/workloads.db`

Record simulation data as you explore the design space. The table must contain at least 10 rows covering at least 4 distinct workloads, with at least 4 paired simulation entries (rows where `paired_workload` is not null). All values must be positive; `num_int_regs` and `num_fp_regs` must be > 32.

### 2. Write `/app/results.json`

```json
{
  "clusters": [
    {
      "cluster_id": 0,
      "core_config": {
        "width": <int>,
        "rob_size": <int>,
        "num_int_regs": <int>,
        "num_fp_regs": <int>
      },
      "area_per_core": <int>,
      "power_per_core_watts": <float>,
      "assigned_workloads": ["<workload_a>", "<workload_b>"],
      "solo_ipc": {"<workload_a>": <float>, "<workload_b>": <float>},
      "interference_adjusted_ipc": {"<workload_a>": <float>, "<workload_b>": <float>}
    }
  ],
  "total_area": <int>,
  "total_power_watts": <float>,
  "weighted_throughput": <float>,
  "experiments_run": <int>
}
```

The `clusters` array must contain exactly 4 entries with `cluster_id` values 0 through 3. `total_area` must equal the sum of `area_per_core * 2` across clusters. `total_power_watts` must equal the sum of `power_per_core_watts * 2` across clusters. `weighted_throughput` must equal the sum of `priority_weight * interference_adjusted_ipc` across all assigned workloads.