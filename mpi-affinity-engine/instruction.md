An MPI process affinity configuration engine at `/app/` simulates Intel MPI process pinning for hybrid MPI+OpenMP workloads on multi-socket NUMA architectures. Given hardware topology descriptions (in `/app/configs/`) and job parameters, it generates per-rank CPU affinity masks, Intel MPI environment variable scripts (`I_MPI_PIN_DOMAIN`, `I_MPI_PIN_ORDER`, `KMP_AFFINITY`, etc.), and placement diagnostic reports.

The engine has multiple bugs that produce incorrect configurations on real-world hardware topologies, and one placement policy is unimplemented. Identify and fix all issues so the tool works correctly across the provided topologies, including systems with multiple NUMA nodes per socket (AMD EPYC NPS2 with interleaved physical core numbering across CCDs), HyperThreading-enabled processors, and multi-socket configurations.

The topology configurations model real hardware:
- `dual_epyc_nps2.json`: AMD EPYC dual-socket with 2 NUMA nodes per socket (NPS2 mode), interleaved core IDs across CCDs, SMT enabled
- `single_xeon_ht.json`: Single-socket Intel Xeon with HyperThreading
- `dual_xeon_nps1.json`: Dual-socket Intel Xeon, 1 NUMA node per socket, no SMT

Source code: `/app/affinity_engine/`  
Entry point: `/app/main.py`