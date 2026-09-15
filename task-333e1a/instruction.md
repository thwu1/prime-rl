The file `/app/chess_core.py` provides a chess move generation library derived from the sunfish engine. It uses a 120-character padded string board representation where the board is always rotated so the current player's pieces are uppercase (king-capture engine model). Key exports:

- `Position` class with `gen_moves()`, `move()`, `rotate()`, `value()` methods
- `from_fen()` for FEN string parsing
- `parse_square()` / `render_square()` for coordinate conversion
- `can_kill_king()` for legality filtering
- Constants: `A1`, `H1`, `A8`, `H8`, `N`, `E`, `S`, `W`, `initial`, `MATE_LOWER`, `MATE_UPPER`, `piece`, `pst`

The file `/app/test_suite.json` contains 8 chess positions in JSON format, each with fields `id`, `fen`, `expected_moves` (array of acceptable UCI moves), `depth`, and `type`.

Build a UCI chess engine and an automated benchmarking pipeline:

**Engine** (`/app/engine.py`): Imports from `chess_core` and implements game tree search (alpha-beta or MTD-bi with transposition table). Must support UCI commands: `uci` → `uciok`, `isready` → `readyok`, `quit`, `position fen <FEN> [moves ...]`, `position startpos [moves ...]`, `go depth <N>` → `bestmove <move>`. Moves in UCI long algebraic notation (e.g., `e2e4`, `e7e8q`). Must correctly map between UCI absolute coordinates and the internal rotated representation. Must reliably find forced checkmates (mate-in-1 at depth 4, mate-in-2 at depth 6) and distinguish checkmate from stalemate. All output flushed immediately.

**Benchmark pipeline** (`/app/run_suite.sh`): An executable shell script that parses positions from `/app/test_suite.json`, runs the engine on each via UCI protocol, compares bestmoves against expected moves, and stores per-position results in a SQLite database at `/app/results.db`. The `results` table must have columns: `id TEXT`, `fen TEXT`, `expected_moves TEXT`, `engine_move TEXT`, `correct INTEGER`, `depth INTEGER`, `time_ms INTEGER`.

**Build system** (`/app/Makefile`): Target `test` runs the benchmark pipeline to produce `results.db`. Target `report` queries the database with `sqlite3` and pipes the output through `jq` to generate `/app/report.json` — a JSON object with fields `total` (int), `correct` (int), `accuracy` (float, percentage), and `positions` (array of per-position result objects). Target `clean` removes generated artifacts.