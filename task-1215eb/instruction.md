Build a solver pipeline for the One-Sided Crossing Minimization (OCM) problem that formulates each instance as an Integer Linear Program in CPLEX LP format, solves it with the pre-installed `glpsol` (GLPK) command-line solver, and records all results in a SQLite database.

## Problem

Given a bipartite graph G = (A ∪ B, E), vertices of A are fixed at integer positions 1..|A| on a horizontal line. Find a permutation of B vertices along a parallel line that **minimizes** the total number of edge crossings in a straight-line drawing. Two edges (a₁, b₁) and (a₂, b₂) with a₁ ≠ a₂ and b₁ ≠ b₂ **cross** iff exactly one of: a₁ < a₂ ∧ pos(b₁) > pos(b₂), or a₁ > a₂ ∧ pos(b₁) < pos(b₂). This problem is NP-hard.

## Input

Instance files at `/app/instances/instance_XX.gr` in PACE `.gr` format:

- `c` lines are comments (ignored).
- p-line: `p ocr n0 n1 m` where n0 = |A|, n1 = |B|, m = |E|.
- Vertices in A: 1..n0. Vertices in B: n0+1..n0+n1.
- Each subsequent non-comment line `x y` defines an edge (x ∈ A, y ∈ B).

## Required Outputs

**ILP models** — For each instance, write a CPLEX LP format file at `/app/models/instance_XX.lp` encoding the OCM problem as a binary ILP. These files must be valid input for `glpsol --lp`. The corresponding `glpsol` output must be saved at `/app/models/instance_XX.out`.

**Solution files** — For each instance, write `/app/solutions/instance_XX.sol` containing exactly n1 lines, where line i holds the B-vertex number placed at position i. All solutions must achieve the **minimum** possible crossing number — non-optimal solutions are rejected.

**Results database** — Create a SQLite database at `/app/results.db` with two tables:
- `instances` with columns: `name` (TEXT, primary key), `n_a` (INTEGER), `n_b` (INTEGER), `n_edges` (INTEGER)
- `solutions` with columns: `instance_name` (TEXT, primary key), `crossings` (INTEGER), `permutation` (TEXT — comma-separated vertex order), `solve_status` (TEXT — the glpsol solver status)

## Environment

There are 6 instances with |B| ranging from 4 to 22. `glpsol` (GLPK), `sqlite3`, and `python3` are pre-installed.