An HLS (High-Level Synthesis) design space exploration framework is provided in `/app/`:

- `/app/dse_space.yaml` -- Configuration search space (clock, pipeline, dataflow, unrolling, partitioning, allocation, DSP mode, strategy).
- `/app/designs/` -- Five benchmark design specs (JSON) with base parameters and human-optimized reference PPA.
- `/app/cost_model.py` -- `evaluate_config(design, config)` returns per-stage pass/fail and PPA metrics for synthesizable configurations. Also exports `compute_composite_area` and FPGA resource limits.

Build a Make-orchestrated pipeline that exhaustively evaluates the configuration space and performs multi-objective optimization analysis. The pipeline must produce:

`/app/Makefile` -- Targets: `all`, `evaluate`, `optimize`, `statistics`, `report` with correct inter-target dependencies. Invokes `/app/dse_tool.py`.

`/app/dse_tool.py` -- CLI tool accepting `--mode {evaluate,optimize,statistics,report}`.

All output goes to `/app/output/`:

`full_results.csv` -- One row per design x configuration (full Cartesian product). Columns: `design`, all config parameters, `compile_pass`, `sim_pass`, `synth_pass`, and PPA metrics (`latency_ns`, `luts`, `ffs`, `dsps`, `brams`, `power_mw`, `composite_area`) populated for synthesizable rows.

`pareto_fronts.json` -- Keyed by design name. Each entry: `num_pareto_points` (int), `pareto_points` (list of dicts with `config`, PPA metrics, and `differential_ppa`). Differential PPA keys: `latency_ns`, `luts`, `ffs`, `power_mw` -- each `(generated - reference) / reference * 100`. Non-dominated set: no other synthesizable config is <= in all three objectives (latency_ns, composite_area, power_mw) and strictly < in at least one.

`pass_at_k.json` -- Keyed by design name. Each entry: `n_total`, `n_compile`, `n_sim`, `n_synth`, and `{stage}_pass_at_{k}` for stages {compile, sim, synth} and K in {1, 5, 10}. Pass@K: probability of at least one stage-passing config when drawing K without replacement from the full set.

`dse_summary.json` -- Keyed by design name. Each entry: `n_total_configs`, `n_synthesizable`, `n_pareto_points`, `hypervolume` (dominated volume of the non-dominated set in latency_ns x composite_area x power_mw space; reference point = 1.1x per-design maximum among synthesizable configs per objective), `dse_improvement_gt_20pct` (bool -- any non-dominated point has differential PPA < -20%), `best_improvements_pct` (dict of best improvements for latency_ns, luts, ffs, power_mw).