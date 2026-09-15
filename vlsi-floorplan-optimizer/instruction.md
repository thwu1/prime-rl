Given floorplanning instances at `/app/instances/*.json`, create `/app/optimizer.py` containing a `FloorplanOptimizer` class with a `solve(self, instance)` method that produces overlap-free block placements minimizing the ICCAD FloorSet cost function. The total weighted score across all instances (computed via `python3 /app/run_evaluation.py`) must be <= 3.0.

## Interface

The `solve(self, instance)` method receives the parsed JSON instance dict and must return a list of `[x, y, width, height]` for each block.

In addition to the returned placement, the optimizer must produce the following artifacts in `/app/output/` for each instance (keyed by `instance["name"]`):

- `<name>.metis`: The instance's block connectivity represented as a valid METIS-format weighted graph, suitable as input for `gpmetis` (pre-installed).
- `<name>.metis.part.<k>`: Result of running `gpmetis` on the above graph with k >= 2 partitions.
- `<name>.pl`: Placement in Bookshelf `.pl` format — header line `UCLA pl 1.0`, then `block_<i> <x> <y> : N` per block. Preplaced blocks (type 2) must have the `/FIXED` suffix.
- `<name>.png`: A PNG visualization of the final placement with blocks colored by their partition assignment. `gnuplot` is pre-installed.

## Instance Format

Each JSON instance contains: `name`, `block_count`, `area_targets` (per-block float), `block_types` (0=soft, 1=fixed-shape, 2=preplaced), `target_dims` (`[w, h]`), `target_pos` (`[x, y]`), `b2b_edges` (`[src, dst, weight]` block-to-block connectivity), `p2b_edges` (`[pin_idx, block_idx, weight]`), `pin_positions` (`[x, y]`), `mib_groups` (identical-dimension groups), `cluster_groups` (abutment groups), `boundary_constraints` (bitmask: 1=left, 2=right, 4=top, 8=bottom), `baseline_hpwl`, `baseline_area`.

## Cost Function

`Cost = (1 + 0.5 * (HPWL_gap + Area_gap)) * exp(2 * V_rel)` where HPWL_gap and Area_gap are relative gaps vs. baseline (clamped >= 0), V_rel is normalized soft constraint violation. Hard violations (overlaps, area tolerance > 1%, wrong fixed/preplaced dims) yield Cost = 10.0. Total score uses exponential weighting: `sum(cost_i * exp(n_i/12)) / sum(exp(n_j/12))`.

The evaluator is at `/app/evaluator.py` and the runner at `/app/run_evaluation.py`.

## Goal

Achieve total weighted score <= 3.0 via `python3 /app/run_evaluation.py`. All output artifacts listed above must exist in `/app/output/`.