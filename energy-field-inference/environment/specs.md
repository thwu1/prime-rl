# Lux AI S3 Energy Field Specification

## Overview

Energy nodes on a 24×24 grid emit energy fields. The field value at each tile determines how much energy units on that tile gain or lose per turn.

## Energy Nodes

- There are 6 energy node slots (indices 0–5).
- Nodes 0–2 are **primary**; nodes 3–5 are their **symmetric mirrors**.
- For a primary node at grid position (a, b), its mirror is at position **(23−b, 23−a)**.
- Both nodes in a pair have **identical** function type and parameters.
- A node is either **active** (contributes to the field) or **inactive** (contributes nothing).
- Pairs are always jointly active or inactive: if node i (i ∈ {0,1,2}) is active, node i+3 is also active, and vice versa.

## Energy Node Functions

Each active node has a function specification defined by four values: **(fn_type, x, y, z)**.

**Function type 0** (sinusoidal):

    f(d) = sin(d · x + y) · z

**Function type 1** (rational):

    f(d) = (x / (d + 1) + y) · z

Here **d** is the Euclidean distance from the tile to the node:

    d = sqrt((tile_x − node_x)² + (tile_y − node_y)²)

## Energy Field Computation

The complete energy field is computed in five steps:

### Step 1 — Per-node contributions

Create a 3D array **C** of shape (6, 24, 24). For each node n in 0..5:
- If node n is **active**: C[n, x, y] = f_n( distance( tile(x,y), node_n ) )
- If node n is **inactive**: C[n, x, y] = 0.0

### Step 2 — Mean adjustment

Compute **μ** = arithmetic mean of ALL 3456 elements of C (all 6 node layers × 24 × 24 tiles, including zeros from inactive nodes).

- If μ < 0.25: add (0.25 − μ) to **every** element of C — active and inactive nodes alike.
- If μ ≥ 0.25: no adjustment.

### Step 3 — Summation

Sum across the node dimension to produce a 2D field:

    E[x, y] = C[0, x, y] + C[1, x, y] + ... + C[5, x, y]

### Step 4 — Rounding

Round each E[x, y] to the nearest integer (half-to-even / banker's rounding).

### Step 5 — Clipping

Clip each value to the range **[−20, 20]**.

## Coordinate System

Grid positions are (x, y) with x ∈ {0, …, 23} and y ∈ {0, …, 23}.

## Observation Format

Each observation entry `{"x": a, "y": b, "energy": e}` records the final integer energy value at grid position (a, b) after all five computation steps.

## Data Format

Each scenario file contains:
- `map_width`, `map_height`: always 24
- `num_active_node_pairs`: how many primary+mirror pairs are active (1, 2, or 3)
- `observations`: list of observed tile entries
