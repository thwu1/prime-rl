A heterogeneous fleet of three systolic array accelerators is described in `/app/fleet.json`. Each accelerator has distinct array dimensions, scratchpad/accumulator capacities, and DMA characteristics that create different performance trade-offs for different workload shapes.

A cycle-accurate simulator binary is provided at `/app/accel_sim`. It evaluates the execution cost of tiled matrix multiplications on any accelerator configuration. Run `/app/accel_sim --help` for interface documentation.

A workload computation graph with inter-operation data dependencies is specified in `/app/dag.json`. Cross-accelerator data transfer costs follow the model in `/app/topology.json`: when a dependency crosses accelerators, the transfer cost is `base_latency + ceil(source_M * source_N / bandwidth)` cycles. Same-accelerator transfers cost zero.

Each accelerator executes one workload at a time. Workloads are scheduled in ID order (w0 through w9, a valid topological sort of the DAG). Each workload's start time is `max(accelerator_free_time, max_over_predecessors(predecessor_end_time + transfer_cost))`.

Produce `/app/schedule.json` containing the globally optimal workload-to-accelerator assignment, optimal per-assignment tiling, and complete schedule that minimizes makespan (completion time of the last workload):

```json
{
  "assignments": [
    {
      "workload_id": "<id>",
      "accelerator_id": "<id>",
      "tiling": {"i_tile": <int>, "j_tile": <int>, "k_tile": <int>},
      "compute_cycles": <int>,
      "start_time": <int>,
      "end_time": <int>
    }
  ],
  "makespan": <int>
}
```

Each tiling must satisfy double-buffered memory constraints (half of total capacity per buffer) and achieve the minimum possible cycle count for that workload on its assigned accelerator. The makespan must be globally optimal over all possible workload-to-accelerator assignments.

The GLPK optimization solver is available as `glpsol`.