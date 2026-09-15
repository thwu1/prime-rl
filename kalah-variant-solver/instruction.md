Build a game-theoretic solver for Kalah (Mancala) that produces exact optimal-play solutions across multiple rule variants, cross-validates them through a compiled C shared-library FFI bridge, and generates game-tree visualizations.

## Environment

`/app/problems.json` defines 9 problem configurations varying in board size, capture rules, objectives, starting positions, and pie-rule applicability. `/app/engine/kalah_engine.c` is the reference C implementation (compiled CLI at `/app/kalah-engine`). The C engine is authoritative for sowing, capture, extra-turn, store-skipping, and endgame-collection semantics.

## Required Outputs

**`/app/libkalah.so`** — Shared library exposing Kalah game logic as ctypes-callable C functions. Build from the engine source, exporting: `kalah_init(int pits, int seeds, int captures)`, `kalah_load(int pits, int captures, int *board, int board_len, int player)`, `kalah_play(int local_pit)` returning int status, and `kalah_get_score()` returning int (SS−NS).

**`/app/results.json`** — `{"results": [...]}` where each entry contains `id` (str), `game_theoretic_value` (int, SS−NS under optimal play), `optimal_first_move` (int, 0-based from mover's perspective), `all_move_values` (dict mapping pit index strings to game-theoretic values), `principal_variation` (list of `{"player": "south"|"north", "pit": int}` through termination). Pie-rule problems additionally include `pie_rule_value` (int) and `pie_rule_optimal_opening` (int).

**`/app/analysis.db`** — SQLite database with tables: `solutions(problem_id TEXT PK, game_theoretic_value, optimal_first_move, pv_length, pie_rule_value, pie_rule_optimal_opening)`, `move_values(problem_id, move_index, value)`, `principal_variations(problem_id, step, player, pit)`, `tree_stats(problem_id PK, nodes_evaluated, unique_positions, max_depth, branching_factor REAL)`.

**`/app/validation_report.json`** — Cross-validation by replaying each PV through `libkalah.so` via ctypes: `[{"problem_id", "moves_validated", "engine_final_score", "solver_final_score", "match": bool}]`.

**`/app/game_analysis.svg`** — gnuplot SVG chart of per-problem game-tree metrics (unique positions, max depth, branching factor).

## Game Semantics

Board uses linear indexing: `0..n-1` South pits, `n` South store, `n+1..2n` North pits, `2n+1` North store. Opposite of position `p` is `2n-p`. Study the C engine source for complete move mechanics including sowing direction, store-skipping, capture conditions, extra-turn triggers, and endgame seed collection.

**Variants:** standard captures vs. no-capture (FairKalah); normal vs. misère objectives. In misère, South minimizes SS−NS while North maximizes it.

**Pie rule:** South picks opening move `m` maximizing `min(Vm, −Vm)`. Pie-rule value = `−min_m(|Vm|)`; optimal opening = `argmin_m(|Vm|)`, smallest pit index breaks ties.