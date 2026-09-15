A correct standard chess perft (performance test) calculator is at `/app/perft.c` with build system `/app/Makefile`. It computes extended perft statistics (nodes, captures, ep, castles, promotions, checks, checkmates) for standard chess positions with hardcoded king-on-e-file castling logic.

Extend this calculator to fully support Chess960 (Fischer Random Chess) and deliver the engine as both a standalone binary and a position-independent shared library with a Python FFI bridge. In Chess960, the back-rank pieces start in any of 960 legal arrangements (king always between the two rooks, bishops on opposite colors). Castling is generalized: regardless of starting squares, the king always ends on g-file (kingside) or c-file (queenside), and the rook on f-file (kingside) or d-file (queenside).

Your implementation must handle:

- **X-FEN castling notation**: file letters A-H (white) and a-h (black) identify which rook can castle. Standard KQkq refers to the outermost rook on each side of the king.
- **Path clearance**: all squares in the span from king's origin/destination to rook's origin/destination must be empty, excluding the castling king and rook themselves.
- **Attack safety**: the king must not start on, pass through, or end on a square attacked by the opponent.
- **Edge cases**: king may already be on its destination (king stays, only rook moves); rook destination may coincide with king's origin; king and rook may swap squares.

Standard chess perft must remain correct after your changes. Verify against: initial position depth 5 = 4865609 nodes, Kiwipete depth 4 = 4085603 nodes.

Produce these deliverables:

- `/app/Makefile` — updated build system with an `all` target that produces both the standalone `/app/perft` binary and `/app/libperft960.so` from the same C source
- `/app/libperft960.so` — the perft engine compiled as a position-independent shared library, with `parse_fen` and `perft` visible as dynamic symbols (inspectable via `nm -D`)
- `/app/perft960.h` — C header declaring the public API struct definitions (`Board`, `Stats`) and function prototypes for external consumers of the shared library
- `/app/perft_bridge.py` — Python module that loads `libperft960.so` via `ctypes`, maps the C struct memory layouts to ctypes `Structure` subclasses, and exposes a callable `run_perft(fen: str, depth: int) -> dict` returning all seven extended statistics as a dictionary
- `/app/valgrind_report.txt` — complete output of running the standalone binary under `valgrind --tool=memcheck` on at least one Chess960 position at depth 3, with the ERROR SUMMARY showing zero errors
- `/app/results.json` — extended perft statistics at depth 4 computed through the Python ctypes bridge for these Chess960 positions:

```json
{
  "pos1": {"fen": "nrkbbqrn/pppppppp/8/8/8/8/PPPPPPPP/NRKBBQRN w BGbg - 0 1", "depth": 4, "nodes": ..., "captures": ..., "ep": ..., "castles": ..., "promotions": ..., "checks": ..., "checkmates": ...},
  "pos2": {"fen": "rbbkrqnn/pppppppp/8/8/8/8/PPPPPPPP/RBBKRQNN w AEae - 0 1", "depth": 4, ...},
  "pos3": {"fen": "qnrbbnkr/pppppppp/8/8/8/8/PPPPPPPP/QNRBBNKR w HChc - 0 1", "depth": 4, ...}
}
```