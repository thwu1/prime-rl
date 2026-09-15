Three game descriptions in Game Description Language (GDL) are provided at `/app/games/`: `tictictoe.kif` (simultaneous two-player tic-tac-toe variant), `connectFour.kif` (8-column, 6-row Connect Four), and `maze.kif` (single-player maze puzzle). GDL is a first-order logic language for specifying game rules using S-expression syntax (KIF format), `;` line comments, and `?`-prefixed variables.

GDL predicates: `role` (player identifier), `init` (initial state proposition), `true` (state reference in rule bodies), `does` (action reference in rule bodies), `legal` (legal moves), `next` (successor state propositions), `terminal` (game-end condition), `goal` (numeric score), `<=` (implication: head if body), `not` (negation), `or` (disjunction), `distinct` (term inequality). The `base` and `input` declarations are metadata and do not affect game execution.

## Deliverables

### 1. Python GDL Reasoner — `/app/gdl_reasoner/`

A Python package exporting `GDLReasoner` that can parse and correctly evaluate any conformant GDL game description:

```python
from gdl_reasoner import GDLReasoner
r = GDLReasoner(gdl_text)              # parse from string
r = GDLReasoner.from_file(path)        # parse from file
r.get_roles() -> list[str]
r.get_initial_state() -> frozenset[str]
r.get_legal_moves(state, role) -> set[str]
r.get_next_state(state, moves) -> frozenset[str]
r.is_terminal(state) -> bool
r.get_goal(state, role) -> int
```

States are `frozenset[str]` of normalized S-expressions with single spaces (e.g., `"(cell 1 1 b)"`, `"(control red)"`). Atomic terms are bare strings (e.g., `"noop"`). The `moves` parameter is `dict[str, str]` mapping role name to move string.

### 2. GDL-to-Prolog Compiler — `/app/gdl2prolog.py`

Usage: `python3 /app/gdl2prolog.py <input.kif> <output.pl>`

Translates a `.kif` game description into a valid SWI-Prolog program (`/usr/bin/swipl` is available). The generated `.pl` must provide predicates `role/1`, `init/1`, `legal/2`, `next/1`, `terminal/0`, and `goal/2`. State-dependent predicates operate against dynamically asserted `true/1` (state propositions) and `does/2` (player actions) facts.

### 3. Maze Optimal Solution — `/app/maze_solution.json`

Compute the shortest action sequence for the robot to achieve goal value 100 in the maze game. Write:

```json
{"actions": ["<action1>", ...], "final_goal": 100, "total_steps": <int>}
```