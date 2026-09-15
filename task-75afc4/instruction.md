PuzzleScript game definition files are provided in `/app/games/`, with a detailed format specification at `/app/format_spec.md`. Each game uses a domain-specific language describing objects, collision layers, pattern-rewrite rules with directional matching, and win conditions.

For each game `<name>.pzl` and each level N (0-indexed), produce three outputs:

- `/app/solutions/<name>_level<N>.txt` — the **optimal** (minimum-move) solution. One move per line: `up`, `down`, `left`, or `right`. The sequence must be the shortest possible that reaches a winning state.

- `/app/proofs/<name>_level<N>.json` — a machine-verifiable **formal proof** that no solution with fewer moves exists. Required JSON fields: `optimal_length` (int — the length of the optimal solution), `proven_optimal` (bool — must be `true`), `proof_method` (string — non-empty description of the verification approach used), `shorter_solution_feasible` (string — must be `"infeasible"`, confirming that no shorter move sequence can win).

- `/app/graphs/<name>_level<N>.dot` — a **Graphviz DOT** digraph of the explored state space. Nodes represent game states, directed edges are labeled with the move direction (`up`/`down`/`left`/`right`). Must contain a path from an initial-state node to a winning-state node and be valid input to the `dot` layout engine.

Games to solve and formally verify: `sokoban.pzl` (2 levels), `painter.pzl` (2 levels), `colorsort.pzl` (2 levels) — 6 levels total.