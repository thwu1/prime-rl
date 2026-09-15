
# Lux AI Season 3 — Game Mechanics Specification

## Overview

Two teams compete on a 24x24 grid in a best-of-5 match sequence (a "game"). Each match lasts 100 timesteps. Parameters are randomized per game and fixed across all 5 matches. Some parameters are observable; others are hidden and must be inferred from gameplay.

## Map

The map is 24x24. Tile types:
- **Empty (0)**: Normal passable tiles.
- **Nebula (1)**: Passable. Reduce vision power by `nebula_tile_vision_reduction`. Reduce unit energy by `nebula_tile_energy_reduction` per step.
- **Asteroid (2)**: Impassable. Block movement and spawning.

### Tile Drift

Nebula and asteroid tiles drift diagonally over time. Drift occurs at timestep `s` when:
```
(s - 1) * |nebula_tile_drift_speed| % 1 > s * |nebula_tile_drift_speed| % 1
```
When drift occurs, the entire tile_type map shifts by `(sign(speed), -sign(speed))` using circular wrapping (like `numpy.roll`).

## Energy Nodes

3-6 energy nodes per map (symmetric pairs). Each node has a position and a function that computes energy contribution based on distance:
- **Function 0**: `sin(d * x + y) * z`
- **Function 1**: `(x / (d + 1) + y) * z`

where `d` = Euclidean distance from tile to node, and `x, y, z` are function parameters.

### Energy Field Computation

For each tile, sum contributions from all active energy nodes. If the global mean is < 0.25, add `(0.25 - mean)` to all values. Round to nearest integer, clip to [-20, 20]. This field is recomputed every timestep (since nodes can drift).

### Energy Node Drift

Energy nodes drift when:
```
(s - 1) * |energy_node_drift_speed| % 1 > s * |energy_node_drift_speed| % 1
```
When drift occurs, each node's position changes by a random delta in `[-energy_node_drift_magnitude, +energy_node_drift_magnitude]` (rounded to integer), clipped to map bounds. Deltas for the second half of nodes are symmetric: `(-delta_y_of_pair, -delta_x_of_pair)`.

## Units

- Max 16 per team. Spawn at (0,0) for team 0, (23,23) for team 1.
- Spawn every `spawn_rate` (3) steps when team has fewer than max units.
- Initial energy: 100. Max: 400. Min: 0 (units with energy < 0 are removed next step).

### Actions

Each unit takes one action per step, encoded as `[action_type, sap_dx, sap_dy]`:
- **0 (center)**: No-op, no energy cost.
- **1 (up)**: Move (0, -1), costs `unit_move_cost` energy.
- **2 (right)**: Move (+1, 0), costs `unit_move_cost` energy.
- **3 (down)**: Move (0, +1), costs `unit_move_cost` energy.
- **4 (left)**: Move (-1, 0), costs `unit_move_cost` energy.
- **5 (sap)**: Ranged attack at `(unit_x + sap_dx, unit_y + sap_dy)`.

Movement into asteroids is blocked (no energy cost). Movement off map edge clips position but still costs energy.

### Sap Actions

Costs `unit_sap_cost` energy to the sapper. Requires energy >= `unit_sap_cost`. Range: `max(|sap_dx|, |sap_dy|) <= unit_sap_range` (Chebyshev distance).

- **Direct hit**: All enemies on target tile lose `unit_sap_cost` energy per sapper targeting that tile.
- **Adjacent hit**: All enemies on the 8 tiles surrounding the target lose `int(unit_sap_cost * unit_sap_dropoff_factor * count)` energy, where `count` = number of sappers whose target is adjacent to the enemy.

Multiple sappers targeting the same/nearby tiles stack: count total hits, then apply damage once with integer truncation.

### Collisions

At end of turn, if opposing teams occupy the same tile: the team with higher **aggregate energy** (sum of all units' energies on that tile) survives; the other team's units on that tile are removed. If tied, all units removed. Collision uses energy from **after movement, before sap** (original energy snapshot).

### Energy Void Fields

Each unit emits a void field to the 4 cardinally adjacent tiles. Void strength at a tile = sum of `original_energy` of all adjacent opposing units. A unit loses `floor(unit_energy_void_factor * opposing_void_strength / friendly_unit_count_on_tile)` energy. Void uses **original energy** (post-move, pre-sap) and **pre-collision unit counts**.

### Energy Update

After combat, each unit gains energy equal to `energy_field[x, y] - nebula_tile_energy_reduction` (if on a nebula tile). Energy is clipped to [0, 400].

### Vision

Vision power at tile `(tx, ty)` from unit at `(ux, uy)`:
```
power = 1 + unit_sensor_range - max(|tx - ux|, |ty - uy|)
```
Plus +10 bonus at the unit's exact position. Contributions from all friendly units sum. At nebula tiles, subtract `nebula_tile_vision_reduction`. Tile is visible if total vision power > 0.

## Match Resolution Order (per timestep)

1. Compute energy field from energy nodes
2. Remove dead units from previous step (energy < 0) and all units if match just reset
3. Spawn relic nodes per schedule
4. Move units (deduct energy)
5. Save original energy snapshot
6. Execute sap actions (using original energy for validity checks)
7. Resolve collisions (using original energy for aggregate comparison)
8. Apply energy void fields (using original energy for void strength)
9. Apply energy field + nebula reduction
10. Spawn new units if `match_steps % spawn_rate == 0`
11. Compute vision power maps
12. Drift tiles and energy nodes
13. Score relic points
14. Check match end; increment step counters

## Observable vs Hidden Parameters

**Observable** (given in `known_params`):
`max_units`, `match_count_per_episode`, `max_steps_in_match`, `map_height`, `map_width`, `num_teams`, `unit_move_cost`, `unit_sap_cost`, `unit_sap_range`, `unit_sensor_range`

**Hidden** (must be inferred):
`nebula_tile_drift_speed`, `nebula_tile_energy_reduction`, `nebula_tile_vision_reduction`, `unit_sap_dropoff_factor`, `unit_energy_void_factor`, `energy_node_drift_speed`, `energy_node_drift_magnitude`

## Parameter Ranges

```
nebula_tile_drift_speed: [-0.15, -0.1, -0.05, -0.025, 0.025, 0.05, 0.1, 0.15]
nebula_tile_energy_reduction: [0, 1, 2, 3, 5, 25]
nebula_tile_vision_reduction: [0, 1, 2, 3, 4, 5, 6, 7]
unit_sap_dropoff_factor: [0.25, 0.5, 1.0]
unit_energy_void_factor: [0.0625, 0.125, 0.25, 0.375]
energy_node_drift_speed: [0.01, 0.02, 0.03, 0.04, 0.05]
energy_node_drift_magnitude: [3, 4, 5]
```
