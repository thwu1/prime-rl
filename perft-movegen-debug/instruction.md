A custom chess move generator at `/app/chess_engine.py` produces incorrect perft (performance test) results. The engine uses `python-chess` for board representation and pseudo-legal move enumeration, with custom legality checking that contains multiple bugs across different move categories. The bugs are non-obvious — some are disguised as intentional optimizations.

Stockfish is installed at `/usr/games/stockfish` and serves as the ground-truth reference engine. It speaks the UCI protocol: send `position fen <FEN> [moves <m1> <m2> ...]` followed by `go perft <depth>` to get divide results formatted as `<move>: <count>` lines ending with `Nodes searched: <total>`.

## Deliverables

1. **Perft comparison tool** (`/app/perft_compare.py`): A reusable script that communicates with Stockfish via UCI subprocess I/O, runs the engine's divide function, and recursively compares move-tree node counts to isolate discrepancies. Must accept:
   ```
   python3 /app/perft_compare.py "<fen>" <depth>
   ```
   and print a structured report showing all divergence points with the move path leading to each.

2. **Fixed engine**: All bugs in `/app/chess_engine.py` corrected so that `perft` matches Stockfish exactly for any legal chess position at any depth.

The engine CLI: `python3 /app/chess_engine.py <depth> "<fen>" [moves]`.