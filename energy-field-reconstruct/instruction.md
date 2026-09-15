A competitive game engine (Lux AI Season 3, NeurIPS 2024) places energy source nodes on a 24x24 grid map. Each node generates an energy contribution to every tile based on Euclidean distance, using one of two parametric functions (sinusoidal or rational decay). Nodes are placed with 180-degree rotational symmetry about the map center. The total energy per tile is the sum of all node contributions, clipped to [-20, 20] and truncated toward zero to produce an integer.

Given partial observations of the energy field (tiles visible through fog of war, typically 55-75% coverage), reconstruct the complete 24x24 energy field and determine the number of independent energy nodes (before symmetry doubling).

This requires solving a nonlinear inverse problem: decomposing the observed field into contributions from an unknown number of source nodes, each with unknown position, function type, and parameters -- while handling observation gaps, value clipping, and discrete model selection.

## Files

- `/app/game_mechanics.md` -- Full specification of the energy field model including function types, symmetry constraints, parameter ranges, and clipping rules
- `/app/field_spec.py` -- Reference implementation for computing energy values from known node parameters

## Task

Implement `/app/reconstruct.py` that accepts two command-line arguments:

```
python3 /app/reconstruct.py <input_json_path> <output_json_path>
```

### Input format

The input JSON file contains:

```json
{
  "observed_tiles": {"x,y": energy_value, ...},
  "map_size": 24
}
```

Keys in `observed_tiles` are `"x,y"` coordinate strings; values are integer energy values at tile (x, y).

### Output format

The output JSON file must contain:

```json
{
  "energy_field": [[e_00, e_01, ...], ...],
  "n_nodes": <int>
}
```

- `energy_field`: a 24x24 2D array (list of 24 lists, each of length 24) where `energy_field[x][y]` is the reconstructed integer energy at tile (x, y). The outer dimension is indexed by x (0-23), the inner by y (0-23).
- `n_nodes`: number of **independent** energy nodes (before symmetry doubling; valid range: 1-3).

## Acceptance Criteria

Your solver will be evaluated on 3 randomly generated energy field instances, each with 55-75% tile visibility. For each instance, the solver must complete within 180 seconds. All of the following must hold for every instance:

1. **Execution**: `python3 /app/reconstruct.py <input> <output>` must exit with return code 0 and produce the output JSON file.
2. **Output shape**: `energy_field` must be exactly 24x24 (a list of 24 lists, each of length 24).
3. **Value range**: every value in `energy_field` must be in [-20, 20].
4. **Field RMSE**: the root-mean-square error between the reconstructed field and the ground-truth field must be strictly less than 2.0.
5. **Tile accuracy**: at least 90% of tiles must have absolute error at most 2 compared to ground truth.
6. **Node count**: `n_nodes` must exactly match the true number of independent nodes.
7. **Rotational symmetry**: at least 95% of tiles must satisfy `|energy_field[x][y] - energy_field[23-x][23-y]| <= 1`, reflecting the 180-degree rotational symmetry of the energy model.