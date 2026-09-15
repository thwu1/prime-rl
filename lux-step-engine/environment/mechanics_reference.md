# Lux AI S3 — Single-Step Resolution Engine Reference

## Overview

In Lux AI Season 3, two teams (0 and 1) compete on a 2D grid. Each team controls units (ships) that move, attack, and collect points. The game proceeds in discrete steps. This document specifies how to resolve **one step**: given a game state and actions, produce the resulting state.

## Coordinate System

The map is `map_width × map_height`. Position `(x, y)` where `x` is column (0 = left), `y` is row (0 = top). Valid: `0 ≤ x < map_width`, `0 ≤ y < map_height`.

## Map Tiles

- **tile_type**: `0` (empty), `1` (nebula), `2` (asteroid)
- **energy**: integer energy value at that tile

Asteroid tiles are impassable. Nebula tiles reduce unit energy. Tiles not listed default to `tile_type=0, energy=0`.

## Units

Each unit has: team (0 or 1), id, position `[x, y]`, energy (integer).

## Actions

- **direction**: 0 = center (idle), 1 = up, 2 = right, 3 = down, 4 = left, 5 = sap
- **sap_dx, sap_dy**: offset for sap target (only relevant when direction=5)

## Step Resolution Phases

Execute these seven phases **in order**.

### Phase 1: Movement

For each unit with direction ∈ {1, 2, 3, 4}:
1. Compute target by applying directional offset.
2. **Target out of bounds**: no move, **pay** `unit_move_cost`.
3. **Target is asteroid**: no move, **no cost**.
4. **Otherwise**: move and pay `unit_move_cost`.

Direction 0 and 5 do not trigger movement or movement cost.

### Phase 2: Sap Actions

For each unit with direction = 5:
1. Target position = `(unit.x + sap_dx, unit.y + sap_dy)`.
2. Validity requires: energy ≥ `unit_sap_cost`, Chebyshev distance `max(|sap_dx|, |sap_dy|) ≤ unit_sap_range`, target in bounds.
3. Invalid sap: no effect, no cost.
4. Valid sap:
   - Sapper loses `unit_sap_cost` energy.
   - Each **enemy** on the target tile loses `unit_sap_cost` energy.
   - Each **enemy** on the 8 surrounding tiles loses `unit_sap_cost × unit_sap_dropoff_factor` energy (converted to integer).

Multiple saps stack independently.

### Phase 3: Collision Resolution

For each tile with units from **both** teams:
1. Compute **aggregate energy** per team on that tile.
2. The team with lower aggregate energy loses — all its units on the tile are removed.
3. Ties: see replay data for exact semantics.

### Phase 4: Energy Void Fields

Each surviving unit generates a void field affecting **cardinally adjacent** (up/down/left/right) enemy units.

A 2D void strength map is computed per team by summing energy contributions from that team's units to their cardinal neighbors. Each affected unit's drain is computed from the opposing team's void map at the unit's position, scaled by `unit_energy_void_factor`. Consult the reference implementation or replay data for details on energy snapshots and stacking behavior.

### Phase 5: Tile Energy and Nebula Effects

For each surviving unit:
1. Gain tile energy at current position.
2. If on nebula: lose `nebula_tile_energy_reduction`.
3. Cap energy at `max_unit_energy`.

### Phase 6: Unit Removal

Remove any unit with energy < 0.

### Phase 7: Relic Point Scoring

Each relic node at `(rx, ry)` has a 5×5 config. For row `r`, col `c`: if `config[r][c] == 1`, tile `(rx-2+c, ry-2+r)` is a point tile. The union of all point tiles across relics is computed. Each team scores the count of unique point tiles occupied by at least one surviving unit.

## Engine Input Format

```json
{
  "params": {
    "map_width": 24, "map_height": 24,
    "unit_move_cost": 2, "unit_sap_cost": 40,
    "unit_sap_range": 5, "unit_sap_dropoff_factor": 0.5,
    "unit_energy_void_factor": 0.125, "max_unit_energy": 400,
    "nebula_tile_energy_reduction": 10
  },
  "units": [{"team": 0, "id": 0, "position": [5, 5], "energy": 200}],
  "map_features": {"tiles": [{"x": 6, "y": 5, "tile_type": 0, "energy": 8}]},
  "relic_nodes": [{"position": [12, 11], "config": [[0,0,0,0,0],[0,1,1,1,0],[0,1,1,1,0],[0,1,1,1,0],[0,0,0,0,0]]}],
  "actions": {
    "team_0": [{"unit_id": 0, "direction": 2, "sap_dx": 0, "sap_dy": 0}],
    "team_1": []
  }
}
```

## Engine Output Format

```json
{
  "units": [{"team": 0, "id": 0, "position": [6, 5], "energy": 206, "alive": true}],
  "team_points": [0, 0]
}
```

All input units appear in output (dead units retain last position/energy with `alive: false`).

## Known Parameter Ranges

```
unit_move_cost: 1..5
unit_sap_cost: 30..50
unit_sap_range: 3..7
unit_sap_dropoff_factor: 0.25, 0.5, 1.0
unit_energy_void_factor: 0.0625, 0.125, 0.25, 0.375
nebula_tile_energy_reduction: 0, 1, 2, 3, 5, 25
max_unit_energy: 400
```
