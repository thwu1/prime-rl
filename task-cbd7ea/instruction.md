Raw performance measurement artifacts from a system characterization campaign are in `/app/data/`. The system was profiled using the Empirical Roofline Toolkit (ERT) and the STREAM memory bandwidth benchmark. The ERT measurement parameters are in `/app/data/ert.conf`. Hardware cache topology exported by `hwloc` is in `/app/data/hwloc_topology.xml` (hwloc v2 XML format). The STREAM source code is at `/app/data/stream.c`.

Construct a complete hierarchical roofline model for this system. The model must characterize the performance envelope at each level of the cache hierarchy from the empirical measurements. Note that STREAM's reported bandwidth uses a simplified byte-counting convention that does not account for all data movement at the memory interface.

Use the model to classify each application kernel described in `/app/data/kernels.json` at every level of the memory hierarchy.

Produce two deliverables:

1. `/app/results/roofline_analysis.json` — Numerical model conforming to the schema in `/app/data/output_schema.json`.

2. `/app/results/roofline_chart.svg` — Roofline visualization produced by `gnuplot`, with log-log axes (FLOP/byte vs GFLOP/s), labeled bandwidth ceilings for each cache level (L1, L2, L3, DRAM), labeled compute ceiling, and each kernel's DRAM-level operating point plotted and labeled by name.

Cache topology must be extracted programmatically from the hwloc XML — do not hard-code hardware parameters.