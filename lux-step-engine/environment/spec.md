# Lux AI S3 — Single-Step Resolution Engine Specification

## Overview

In Lux AI Season 3, two teams (team 0 and team 1) compete on a 2D grid map. Each team controls multiple units (ships). The game proceeds in discrete steps. This document specifies how to resolve **one complete step** of the game, transforming a game state and set of actions into the resulting game state.

## Coordinate System

The map is a grid of size `map_width` x `map_height`. Coordinates are `(x, y)` where `x` is the column index (0 = leftmost) and `y` is the row index (0 = topmost). Valid positions satisfy `0 <= x < map_width` and `0 <= y < map_height`.

## Map Tiles

Each tile has two properties:

- **tile_type**: `0` (empty), `1` (nebula), `2` (asteroid)
- **energy**: an integer representing the energy value at that tile

Tiles not explicitly listed in the input default to `tile_type=0, energy=0`.

Asteroid tiles are impassable. Nebula tiles are passable but drain unit energy. Empty tiles are passable with no special effects.

## Units

Each unit belongs to a team (0 or 1) and has:

- **id**: unique identifier within its team
- **position**: `[x, y]` on the map
- **energy**: integer energy level

## Actions

Each unit's action for the step consists of:

- **direction**: integer 0–5
  - `0`: center (stay in place, no cost)
  - `1`: move up (y decreases by 1)
  - `2`: move right (x increases by 1)
  - `3`: move down (y increases by 1)
  - `4`: move left (x decreases by 1)
  - `5`: sap action (unit does not move; see Phase 2)
- **sap_dx, sap_dy**: sap target offset from unit position (only relevant when direction=5)

If a unit has no action entry, it defaults to direction=0 (center).

---

## Step Resolution Phases

The step is resolved by executing the following seven phases **in order**.

### Phase 1: Movement

For each unit with direction in {1, 2, 3, 4}:

1. Compute target position by applying the directional offset to the unit's current position.
2. **If the target is out of map bounds**: the unit does not move, but **still pays** `unit_move_cost` energy.
3. **If the target is an asteroid tile** (tile_type=2): the unit does not move, and **does not pay** any energy cost.
4. **Otherwise** (target is in bounds and not an asteroid): the unit moves to the target position and pays `unit_move_cost` energy.

Units with direction 0 (center) neither move nor pay any energy cost.
Units with direction 5 (sap) do not move; their energy cost is handled in Phase 2.

Note: a unit's energy may go negative as a result of movement.

### Phase 2: Sap Actions

For each unit with direction 5:

1. Compute sap target position: `(unit.x + sap_dx, unit.y + sap_dy)`.
2. Check validity — all of the following must hold:
   - The unit's current energy is `>= unit_sap_cost`
   - The Chebyshev distance to target does not exceed range: `max(|sap_dx|, |sap_dy|) <= unit_sap_range`
   - The target position is within map bounds
3. **If invalid**: the sap does not execute and the unit pays **no** energy cost.
4. **If valid**:
   - The sapping unit loses `unit_sap_cost` energy.
   - Every **enemy** unit on the target tile loses `unit_sap_cost` energy.
   - Every **enemy** unit on any of the **8 tiles surrounding** the target (all orthogonal and diagonal neighbors) loses `floor(unit_sap_cost * unit_sap_dropoff_factor)` energy. Only in-bounds neighbor tiles are considered.
   - "Enemy" means belonging to the opposite team from the sapping unit.

Multiple sap actions targeting the same or overlapping tiles stack independently — each one applies its full damage.

### Phase 3: Collision Resolution

After movement and sap, check every tile for collisions:

For each tile occupied by units from **both** teams:

1. Compute the **aggregate energy** for each team on that tile (sum of all that team's units' energies on the tile).
2. The team with **strictly lower** aggregate energy loses: **all** of that team's units on the tile are removed (marked not alive).
3. **If aggregate energies are exactly equal**: **all** units from **both** teams on the tile are removed.

Removed units do not participate in any subsequent phases.

### Phase 4: Energy Void Fields

Energy void fields are computed **simultaneously** — all drain calculations use the energy values from **before** any void drains are applied.

For each surviving unit U:

- For each of the 4 **cardinally adjacent** tiles (up, down, left, right) that are within map bounds:
  - For each surviving **enemy** unit V at that position:
    - V accumulates a drain of `floor(U.energy * unit_energy_void_factor)`.

After computing all accumulated drains, apply them: each unit's energy is reduced by its total accumulated drain.

### Phase 5: Tile Energy and Nebula Effects

For each surviving unit:

1. The unit gains energy equal to the `energy` value of the tile at its current position.
2. If the tile is a **nebula** (tile_type=1): the unit additionally loses `nebula_tile_energy_reduction` energy.
3. After applying gains and losses, the unit's energy is **capped** at `max_unit_energy` (it cannot exceed this value).

### Phase 6: Unit Removal

Any surviving unit whose energy is **strictly less than 0** is removed (marked not alive).

### Phase 7: Relic Point Scoring

Relic nodes define "point tiles" on the map. Each relic node has a position `(rx, ry)` and a 5x5 binary configuration matrix `config`.

For each relic node, the point tiles are determined by:
- For row `r` in 0..4 and column `c` in 0..4: if `config[r][c] == 1`, then tile `(rx - 2 + c, ry - 2 + r)` is a point tile (provided it is within map bounds).

The set of all point tiles is the union across all relic nodes. A tile that qualifies as a point tile from multiple relic nodes is still counted only once.

For each team, count the number of **unique** point tiles occupied by **at least one surviving unit** of that team. Multiple units on the same point tile still contribute only 1 point.

---

## Input Format

The `resolve_step` function receives a dictionary with the following structure:

```json
{
  "params": {
    "map_width": 24,
    "map_height": 24,
    "unit_move_cost": 2,
    "unit_sap_cost": 40,
    "unit_sap_range": 5,
    "unit_sap_dropoff_factor": 0.5,
    "unit_energy_void_factor": 0.125,
    "max_unit_energy": 400,
    "nebula_tile_energy_reduction": 10
  },
  "units": [
    {"team": 0, "id": 0, "position": [5, 5], "energy": 200},
    ...
  ],
  "map_features": {
    "tiles": [
      {"x": 6, "y": 5, "tile_type": 0, "energy": 8},
      ...
    ]
  },
  "relic_nodes": [
    {"position": [12, 11], "config": [[0,0,0,0,0],[0,0,1,0,0],[0,1,1,1,0],[0,0,1,0,0],[0,0,0,0,0]]}
  ],
  "actions": {
    "team_0": [
      {"unit_id": 0, "direction": 2, "sap_dx": 0, "sap_dy": 0},
      ...
    ],
    "team_1": [
      {"unit_id": 0, "direction": 0, "sap_dx": 0, "sap_dy": 0},
      ...
    ]
  }
}
```

Tiles not listed in `map_features.tiles` default to `tile_type=0, energy=0`.

## Output Format

Return a dictionary:

```json
{
  "units": [
    {"team": 0, "id": 0, "position": [6, 5], "energy": 206, "alive": true},
    ...
  ],
  "team_points": [0, 2]
}
```

The `units` list must contain **all** input units (including removed ones), preserving the original order. Removed units retain their last known position and energy and have `alive: false`.

`team_points` is `[team_0_points, team_1_points]`.

## Parameter Summary

| Parameter | Description |
|---|---|
| `map_width`, `map_height` | Dimensions of the map grid |
| `unit_move_cost` | Energy deducted per successful movement (not charged for asteroid blocks) |
| `unit_sap_cost` | Energy cost to sap; also equals direct sap damage |
| `unit_sap_range` | Max Chebyshev distance for a valid sap target |
| `unit_sap_dropoff_factor` | Multiplier for sap splash damage on the 8 surrounding tiles |
| `unit_energy_void_factor` | Multiplier for energy void drain from adjacent enemies |
| `max_unit_energy` | Maximum energy a unit can hold |
| `nebula_tile_energy_reduction` | Energy drained per step for units on nebula tiles |
