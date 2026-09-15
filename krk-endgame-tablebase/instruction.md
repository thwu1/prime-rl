A KRK (King + Rook vs King) endgame tablebase generator at `/app/krk_tablebase.py` should compute correct Distance-To-Mate values for every legal position and write aggregate statistics to `/app/krk_results.json` with all positions fully resolved.

The current implementation produces incorrect results. Diagnose and fix all defects so that every legal KRK position is correctly classified as either a win for White (with the optimal DTM in plies) or a draw.

See `/app/spec.md` for position encoding and output format. Stockfish is available at `/usr/games/stockfish` for position analysis and cross-validation.