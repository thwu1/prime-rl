# Oil Field Detection Problem

## Overview

There is an island consisting of an N x N grid of cells. The top-left cell has
coordinates (0, 0); cell (i, j) is i rows down and j columns right.

Hidden under the island are M oil fields. Each oil field has a known connected
polyomino shape (given as a list of (row_offset, col_offset) pairs relative to
a placement origin). The shapes are known in advance, but the positions where
each polyomino is placed on the grid are unknown. Oil fields may overlap --
multiple polyominoes can cover the same cell.

For each cell (i, j), define v(i, j) as the number of oil fields covering it.
Your goal is to identify every cell where v(i, j) > 0.

## Operations

Interact with the judge by writing commands to stdout and reading responses
from stdin. You may perform at most 2 * N^2 operations total.

### Drill (exact measurement)

    d i j

Drills cell (i, j) and reveals the exact value of v(i, j).
**Cost: 1**

### Aggregate Query (noisy measurement)

    q k i_1 j_1 i_2 j_2 ... i_k j_k

Queries a set S of k >= 2 cells. Returns a noisy estimate of the total oil
value v(S) = sum of v(i, j) for all (i, j) in S.
**Cost: 1 / sqrt(k)**

**Noise model:** Let v(S) be the true sum and epsilon be the error parameter.

- Mean:     mu = (k - v(S)) * epsilon + v(S) * (1 - epsilon)
- Variance: sigma^2 = k * epsilon * (1 - epsilon)
- Returned value: max(0, round(x))  where x ~ Normal(mu, sigma^2)

Equivalently: mu = k * epsilon + v(S) * (1 - 2 * epsilon).
When epsilon is small, mu is close to v(S) with a small additive bias of
k * epsilon. The standard deviation sqrt(k * epsilon * (1 - epsilon)) grows
with k, creating a trade-off: larger queries are cheaper per cell but noisier.

### Answer (guess)

    a k i_1 j_1 i_2 j_2 ... i_k j_k

Assert that exactly these k cells have v(i, j) > 0.

- If correct: judge responds **1** and the game ends.
- If incorrect: judge responds **0** and the game continues.
  **Cost: 1** (for a wrong guess).

## Protocol

### Input (from judge to solver via stdin)

The judge first sends the problem data:

    N M epsilon
    size_0
    d_00 d_01
    d_10 d_11
    ...
    size_1
    d_00 d_01
    ...

Where:
- N = grid size, M = number of polyominoes, epsilon = noise parameter
- For each polyomino k (0-indexed): first its cell count, then each cell's
  (row_offset, col_offset) on separate lines.

### Solver output (commands)

Write drill, query, or answer commands to stdout. **Flush after every line.**

### Judge responses

After each command, read one line from stdin:
- For `d`: the exact v(i, j) value (integer >= 0)
- For `q`: the noisy observation (integer >= 0)
- For `a`: 1 (correct, game over) or 0 (incorrect, continue)

### Termination

When the judge responds with 1 to an answer command, exit immediately.

## Scoring

Your score for an instance is the total cost of all operations performed.
Normalized score = cost / N^2. Lower is better.

A trivial strategy of drilling every cell costs N^2 (normalized score = 1.0).
A good strategy combining aggregate queries with selective drilling should
achieve normalized scores well below 0.40.

## Architecture Requirements

Your solution must be a multi-tool pipeline:

### 1. C Shared Library

Implement `/app/scoring.c` matching the interface in `/app/scoring.h`. This
library provides the Gaussian log-likelihood scoring kernel used by the beam
search. Compile it into `/app/libscoring.so` using a Makefile (`/app/Makefile`).

The header declares:
- `score_combo()` -- score a single candidate placement combination
- `find_best_combo()` -- find the best among multiple candidates

Build with: `make -C /app`

### 2. Python Solver with ctypes

Implement `/app/solver.py` which loads `/app/libscoring.so` via Python's
`ctypes` module and uses the C scoring functions for the beam search.
The solver communicates with the judge via stdin/stdout.

### 3. Orchestration Pipeline

Create `/app/pipeline.sh` which:
- Builds the C library using `make`
- Runs the solver against each instance in `/app/instances/`
- Uses `jq` to extract fields from the judge's JSON output
- Uses `sqlite3` to store results in `/app/results.db` with this schema:

```sql
CREATE TABLE results (
    instance_name TEXT PRIMARY KEY,
    grid_size INTEGER,
    num_fields INTEGER,
    epsilon REAL,
    solved INTEGER,
    cost REAL,
    normalized_cost REAL,
    num_ops INTEGER
);
```

## Files

- `/app/judge.py` -- interactive judge. Run with:
  `python3 /app/judge.py <instance.json> "<solver_command>"`
- `/app/generate.py` -- instance generator:
  `python3 /app/generate.py <seed> [N] [M] [epsilon]`
- `/app/instances/` -- 5 pre-generated test instances (instance_0.json .. instance_4.json)
- `/app/scoring.h` -- C header for the scoring library interface
- `/app/run_judge.sh` -- test against all instances:
  `bash /app/run_judge.sh "python3 /app/solver.py"`

## Instance Parameters

| Instance | N  | M | epsilon | Notes              |
|----------|----|---|---------|--------------------|
| 0        | 8  | 3 | 0.10    | Small, low noise   |
| 1        | 10 | 3 | 0.15    | Medium             |
| 2        | 10 | 4 | 0.10    | More polyominoes   |
| 3        | 12 | 4 | 0.20    | Overlapping fields |
| 4        | 15 | 5 | 0.15    | Large grid         |

## Example Session (N=4, M=1, epsilon=0.1, polyomino=[(0,0),(0,1),(1,0)])

Suppose the polyomino is placed at (1, 2), covering cells (1,2), (1,3), (2,2).

    Solver                      Judge
    ------                      -----
    (reads header)              4 1 0.1\n1\n3\n0 0\n0 1\n1 0\n
    q 4 0 0 0 1 0 2 0 3        0          (row 0 has no oil; noisy obs)
    q 4 1 0 1 1 1 2 1 3        2          (row 1 has 2 oil cells; noisy obs)
    q 4 2 0 2 1 2 2 2 3        1          (row 2 has 1 oil cell; noisy obs)
    d 1 2                      1          (exact: v(1,2) = 1)
    d 1 3                      1          (exact: v(1,3) = 1)
    d 2 2                      1          (exact: v(2,2) = 1)
    a 3 1 2 1 3 2 2            1          (correct!)
