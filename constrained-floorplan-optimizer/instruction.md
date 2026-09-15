Implement a floorplan optimizer at `/app/optimizer.py` that places rectangular blocks to minimize wirelength (HPWL) and bounding-box area while satisfying hard and soft placement constraints, following the ICCAD contest evaluation methodology.

## Environment

- `/app/evaluator.py` — Evaluation engine with scoring functions and constraint checkers. Study this to understand the exact cost formula and constraint semantics.
- `/app/instances/` — Five JSON test instances (15–48 blocks) with varying constraint combinations.
- `/app/instance_generator.py` — Generator script (format reference).

## Instance Format

Each instance JSON contains: `block_count`, `area_targets`, `b2b_connectivity` (weighted block-to-block nets), `p2b_connectivity` (weighted pin-to-block nets), `pins_pos`, `constraints` (per-block `[fixed, preplaced, mib_id, cluster_id, boundary_code]`), `target_positions` (per-block `[x, y, w, h]`, -1 = free), `baseline_hpwl`, `baseline_area`.

## Optimizer Interface

Run: `python3 /app/optimizer.py` — must read all instances from `/app/instances/`, write solutions to `/app/solutions/solution_{id}.json` as `{"instance_id": <id>, "positions": [[x, y, w, h], ...]}`, and exit 0.

## Scoring

**Hard constraints** (any violation → infeasible, cost = 10.0):
- Zero block overlaps (pairwise intersection area must be zero)
- Soft-block realized area within 1% of target: `|w·h − a| / a ≤ 0.01`
- Fixed-shape blocks: `(w, h)` must exactly match `target_positions`
- Preplaced blocks: `(x, y, w, h)` must all exactly match `target_positions`

**Soft constraints** (violations feed exponential penalty via `V_rel`):
- Boundary: block must touch specified bounding-box edge(s); bitmask encoding (1=left, 2=right, 4=top, 8=bottom)
- MIB: blocks sharing an MIB group ID must have identical `(w, h)`
- Cluster: blocks sharing a cluster group ID must form a single connected component (pairwise edge-sharing)

**Cost**: `Cost = (1 + 0.5·(max(0, HPWL_gap) + max(0, Area_gap))) × exp(2·V_rel)` where gaps are relative to baseline and `V_rel = total_soft_violations / max_possible_soft_violations`.

**Overall score**: exponentially weighted by block count: `Σ Cost_i·exp(n_i/12) / Σ exp(n_j/12)`.

**Thresholds**: each instance cost < 6.0; overall score < 5.0.