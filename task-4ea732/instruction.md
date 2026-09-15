Three CVRP instances are in `/app/data/`. The environment provides GLPK (`glpsol`) for mathematical programming and Graphviz (`neato`) for graph rendering. Build a complete analysis pipeline that produces feasible routing solutions, LP relaxation lower bounds via GLPK, and route visualizations via Graphviz.

**Input format** (each file in `/app/data/`):
```
N V C
d_0 x_0 y_0
d_1 x_1 y_1
...
d_{N-1} x_{N-1} y_{N-1}
```
First line: N locations (including depot), V vehicles, vehicle capacity C. Following N lines: demand d_i, coordinates x_i, y_i. Location 0 is the depot (demand 0). Locations 1..N-1 are customers.

**Required outputs:**

**1. Solution files** at `/app/solutions/vrp_101_10_1.sol`, `/app/solutions/vrp_200_16_1.sol`, `/app/solutions/vrp_421_41_1.sol`:
```
obj opt
0 c_1 c_2 ... 0
0 c_3 c_4 ... 0
...
```
First line: total Euclidean route distance (float), optimality flag (0 or 1). Following V lines: each vehicle's route as location indices starting and ending at depot 0. Every customer 1..N-1 in exactly one route. Per-route demand must not exceed C. Empty routes: `0 0`. Reported objective must match computed Euclidean distance (tolerance 1.0).

**2. GMPL model** at `/app/models/vrp_lp.mod` -- a valid GNU MathProg LP relaxation formulation for CVRP, usable with `glpsol --math` and per-instance data files. Must define LP variables with relaxed bounds, flow/assignment constraints, and output the LP objective.

**3. LP relaxation bounds** at `/app/bounds/vrp_101_10_1.bound`, `/app/bounds/vrp_200_16_1.bound`, `/app/bounds/vrp_421_41_1.bound` -- each containing a single float: the LP relaxation lower bound computed by invoking `glpsol` with the GMPL model. Each bound must be positive and no greater than the corresponding solution objective.

**4. Route visualizations** -- DOT source at `/app/visualizations/vrp_<name>.dot` and rendered SVG at `/app/visualizations/vrp_<name>.svg`. DOT files must define all N nodes with coordinate-based `pos` attributes and edges colored by route. SVG files rendered from DOT via Graphviz `neato` engine with position-preserving layout.

**Quality thresholds** (maximum allowed total Euclidean distance):

| Instance | N | V | C | Max Distance |
|---|---|---|---|---|
| `vrp_101_10_1` | 101 | 10 | 200 | 1050.0 |
| `vrp_200_16_1` | 200 | 16 | 200 | 2000.0 |
| `vrp_421_41_1` | 421 | 41 | 200 | 2500.0 |