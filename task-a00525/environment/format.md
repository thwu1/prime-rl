# N-Queens Completion Instance Format

## Input Format

Each instance file in `/app/instances/` is a JSON object:

- `n` (int): Board size (n x n chessboard)
- `pre_placed` (list of [row, col]): Pre-placed queen positions, 0-indexed
- `id` (string): Unique instance identifier

Pre-placed queens are guaranteed to be mutually non-attacking (no two share a row, column, or diagonal).

## Expected Output Format

Write result files to `/app/results/<id>_result.json` as JSON:

- `id` (string): Same as input instance id
- `satisfiable` (bool): Whether a valid completion exists
- `solution` (list of [row, col] or null): All n queen positions if satisfiable, null otherwise

Solutions must include all pre-placed queens and satisfy all n-Queens constraints:
exactly one queen per row, one per column, no two queens on the same diagonal.
Queen positions should be sorted by row.

## Phase Transition Output Format

Write `/app/results/phase_transition.json` as JSON:

- `board_size` (int): 12
- `results` (list of objects): One entry per m value tested, each with:
  - `m` (int): Number of pre-placed queens
  - `total` (int): Number of instances generated and solved
  - `sat_count` (int): Number found satisfiable
  - `sat_ratio` (float): sat_count / total
- `critical_m` (int): Smallest m where sat_ratio drops below 0.5
