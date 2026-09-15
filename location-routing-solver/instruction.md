Solve the **Location-Routing Problem (LRP)**: jointly decide which depots to open and how to route vehicles from those depots to serve all customers, minimizing total cost (depot setup costs + Euclidean routing distances).

## Environment

Three LRP instances are at `/app/data/instance_{1,2,3}.txt`. GLPK (`glpsol`) is installed. An incomplete GMPL model template is at `/app/models/depot_selection_template.mod` — the objective and basic assignment constraints are provided, but three sections are marked TODO: the depot capacity constraint, the vehicle fleet limit constraint, and the output printf section.

## Input Format

First line: `N M V C` (candidate depots, customers, max vehicles per depot, vehicle capacity). Then `N` depot lines: `setup_cost capacity x y`. Then `M` customer lines: `demand x y`. Customer indices are 0-based.

## Constraints

- Every customer must appear in exactly one route.
- Each route's total demand must not exceed vehicle capacity `C`.
- Each depot's total served demand must not exceed its capacity.
- Number of routes per opened depot must not exceed `V`.
- Only opened depots may have routes.

## Required Artifacts

Produce all of the following:

- `/app/models/depot_selection.mod` — completed GMPL model with all TODO sections implemented (depot capacity constraint, fleet limit constraint, parseable printf output). Must be syntactically valid and solvable by `glpsol`.
- `/app/models/instance_{1,2,3}.dat` — GMPL data files generated from each instance, compatible with the completed model.
- `/app/logs/glpsol_instance_{1,2,3}.log` — execution logs from running `glpsol` on each instance.
- `/app/solutions/instance_{1,2,3}.sol` — final LRP solutions satisfying all constraints above.

## Solution File Format

```
obj opt
o_0 o_1 ... o_{N-1}
r_i
c_1 c_2 ... c_k
r_i
c_p c_q ...
...
```

- Line 1: `obj` (total cost as float) and `opt` (1 if proven optimal, else 0).
- Line 2: space-separated depot opening flags (1=open, 0=closed).
- For each opened depot **in increasing index order**: one line with `r_i` (number of routes), then `r_i` lines each listing customer indices visited in order. Depot-to-first and last-to-depot legs are implicit.

## Quality

Solutions must satisfy all constraints and achieve total cost below 72% of the trivial upper bound (all depots open + individual customer round-trips).