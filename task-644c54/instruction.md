Three VGDL (Video Game Description Language) game descriptions with level files are at `/app/games/`. Java source from the GVGAI reference engine is at `/app/reference/` for specification of VGDL semantics.

Build `/app/vgdl_engine.py` — a Python engine that parses these game descriptions, loads levels, simulates player actions per each game's rules, and finds winning action sequences for all three levels via state-space search.

The engine must expose a CLI:

    python3 /app/vgdl_engine.py trace <game_file> <level_file> <comma_separated_actions>

Output: single-line JSON with fields `tick`, `score`, `game_over`, `win`, `sprites` (list of `{"type","x","y"}` for alive non-hidden sprites), processable by `jq`.

Tests at `/tests/test_state.py` define the expected module API (`GameDescription`, `ForwardModel`, `Solver`) and validate correctness.