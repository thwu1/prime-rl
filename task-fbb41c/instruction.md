Three game description files in GDL/KIF format are provided at `/app/games/`: `ticTacToe.kif` (a simultaneous-move variant), `connectFour.kif` (turn-based with column-stacking), and `breakthrough.kif` (8×8 board with piece movement and captures). These games exercise diverse GDL constructs. SWI-Prolog (`swipl`) and Graphviz (`dot`) are available in the environment.

Build a GDL reasoning engine at `/app/` that can parse these game descriptions, compute game-state properties, and visualize game trees. Your solution must provide:

**`/app/gdl_transpiler.py`** — `transpile(kif_path: str, output_pl_path: str)` — Reads a GDL/KIF game and produces a valid SWI-Prolog program loadable by `swipl` without errors.

**`/app/gdl_query.py`** — `GdlQueryEngine(pl_path: str)` class supporting:
- `get_roles() -> list[str]`
- `get_initial_state() -> frozenset` — each element a tuple of strings representing a ground GDL fact, e.g. `("cell", "1", "1", "b")`
- `get_legal_moves(state: frozenset, role: str) -> set` — move tuples
- `get_next_state(state: frozenset, moves: dict) -> frozenset` — `moves` maps role name to move tuple
- `is_terminal(state: frozenset) -> bool`
- `get_goal(state: frozenset, role: str) -> int`

**`/app/game_explorer.py`** — `explore_and_visualize(pl_path: str, depth: int, dot_output: str, svg_output: str, json_output: str)` — Explores the game tree from the initial state to the specified depth. Produces a valid Graphviz DOT file, renders it to SVG, and writes a JSON analysis containing: `roles`, `total_states`, `total_transitions`, `depth`, `terminal_states_found`, `branching_factor` (average over non-terminal explored states).