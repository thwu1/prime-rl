Three GDL (Game Description Language) game descriptions are provided in `/app/games/`: a simultaneous tic-tac-toe variant (`tictictoe.kif`), Connect Four (`connectfour.kif`), and a robot maze puzzle (`maze.kif`). GDL is a formal logic language used to specify the rules of arbitrary games — roles, initial state, legal moves, state transitions, terminal conditions, and goal values.

Produce three Python modules at `/app/` that together form a complete GDL game analysis system:

**`/app/gdl_reasoner.py`** — A `GDLReasoner` class that reads a GDL/KIF game file and can fully compute game semantics: roles, initial state, legal moves for any state, successor states, terminal detection, and goal values. Required interface:

- `__init__(self, kif_path: str)`
- `get_roles() -> list[str]` (sorted alphabetically)
- `get_initial_state() -> set[str]`
- `get_legal_moves(state: set[str]) -> dict[str, list[str]]` (move lists sorted per role)
- `get_next_state(state: set[str], moves: dict[str, str]) -> set[str]`
- `is_terminal(state: set[str]) -> bool`
- `get_goals(state: set[str]) -> dict[str, int]`

State propositions are parenthesized strings like `'(cell 1 1 b)'`. Moves use the same convention (e.g., `'(mark 1 1)'`, `'(drop 4)'`, `'move'`). The reasoner must correctly handle all GDL constructs present in the three provided games, including negation, disjunction, recursive rules, and the `distinct` relation.

**`/app/gdl_to_prolog.py`** — A `compile_to_prolog(kif_path: str, output_path: str)` function that translates a GDL game into a semantically equivalent SWI-Prolog program. The generated `.pl` file must load in `swipl` without errors and yield correct results when querying `role/1`, `init/1`, and `legal/2` (with game state asserted via `true/1` facts). `true/1` and `does/2` must be declared dynamic. Output goes to `/app/prolog/`.

**`/app/state_graph.py`** — Functions to explore and visualize game trees:

- `generate_state_graph(kif_path: str, output_dot: str, max_depth: int = 3)` — explore the game tree from the initial state up to `max_depth` transitions, producing a Graphviz DOT file where nodes represent game states (labeled with their propositions) and edges represent joint moves. For multi-player games, limit to at most 4 moves per role to bound the graph.
- `render_svg(dot_path: str, svg_path: str)` — compile a DOT file to SVG using the `dot` command.

Output goes to `/app/graphs/`.

SWI-Prolog (`swipl`) and Graphviz (`dot`) are pre-installed in the environment.