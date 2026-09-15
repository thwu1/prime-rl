# Energy Field Model — Lux AI Season 3

## Overview

The game map is a 24×24 grid (coordinates 0–23 on each axis). Energy source nodes are placed on the map, and each node generates an energy field that affects every tile. The total energy at each tile is the sum of contributions from all nodes, clipped to the range [-20, 20] and truncated to an integer.

## Energy Nodes

- There are **1 to 3 independent** energy nodes per game.
- Each independent node has a **symmetric mirror** placed by 180° rotational symmetry about the map center: if an independent node is at position `(nx, ny)`, its mirror is at `(23 - nx, 23 - ny)`.
- Mirror nodes have **identical** function type and parameters as their independent counterpart.
- Total node count (independent + mirrors) ranges from 2 to 6.

## Node Properties

Each node has:
- **Position**: `(nx, ny)` where `0 ≤ nx, ny ≤ 23` (integer coordinates for ground truth; solvers may use continuous positions during fitting)
- **Function type**: `0` or `1`
- **Parameters**: three real-valued coefficients `(a, b, c)`

### Typical Parameter Ranges

Parameter ranges vary by function type.

**Function type 0 (sinusoidal):**
- `a`: magnitude in [0.25, 0.9], either sign (controls spatial frequency)
- `b`: [-1.5, 1.5] (phase shift)
- `c`: [2.5, 5.5] (amplitude, always positive)

**Function type 1 (rational decay):**
- `a`: magnitude in [2.0, 5.0], either sign (controls peak intensity)
- `b`: [-0.3, 0.3] (background level, kept small)
- `c`: [1.0, 3.0] (scaling, always positive)

## Energy Contribution Functions

For a node at position `(nx, ny)` with function type `fn_type` and parameters `(a, b, c)`, the energy contribution to tile `(x, y)` is computed as follows.

The **Euclidean distance** from tile to node:
```
distance = sqrt((x - nx)² + (y - ny)²)
```

**Function Type 0** (sinusoidal):
```
contribution = sin(distance × a + b) × c
```

**Function Type 1** (rational decay):
```
contribution = (a / (distance + 1) + b) × c
```

## Total Energy Computation

The raw energy at tile `(x, y)` is the sum of contributions from **all** nodes (independent + mirrors):

```
raw_energy(x, y) = Σ contribution(x, y, node)   for all nodes
```

The final integer energy value is:

```
energy(x, y) = trunc(clip(raw_energy(x, y), -20, 20))
```

where:
- `clip(v, lo, hi)` clamps `v` to the range `[lo, hi]`
- `trunc(v)` truncates toward zero: `trunc(3.7) = 3`, `trunc(-3.7) = -3`, `trunc(0.9) = 0`, `trunc(-0.9) = 0`

## Symmetry Property

Due to the rotational symmetry of node placement (each node has a mirror at `(23-nx, 23-ny)` with identical parameters):

```
energy(x, y) = energy(23 - x, 23 - y)
```

This identity holds for all tiles on the map (for both raw and integer energy values).

## Node Placement Constraints

In generated game instances, nodes satisfy:
- Positions are at least 2 tiles from the map edges (coordinates 2–21)
- No node is within Manhattan distance 3 of the map center (11.5, 11.5)
- Independent nodes are at least Manhattan distance 5 from each other and from each other's mirrors

## Partial Observations

In-game, tiles are partially observable due to **fog of war**. Observed tiles provide their exact integer energy value. Unobserved tiles have unknown energy values. Typical coverage is 55–75% of the map.

Visibility zones are roughly circular, centered on unit positions, with radii determined by sensor range (game parameter).
