# KRK Endgame Tablebase Specification


## Position Encoding

- Squares numbered 0-63: a1=0, b1=1, ..., h1=7, a2=8, ..., h8=63
- rank(sq) = sq // 8 (0 for rank 1, 7 for rank 8)
- file(sq) = sq % 8 (0 for a-file, 7 for h-file)
- Position tuple: (wk, wr, bk, stm) — white king square, white rook square, black king square, side to move (0=white, 1=black)

## DTM Convention

- DTM measured in plies (half-moves) to checkmate with optimal play
- Checkmate position: DTM = 0
- Winning for white: DTM > 0
- Draw (stalemate or otherwise): DTM = -1

## Required Output

### File: /app/krk_results.json

```json
{
    "total_positions": <int>,
    "white_wins": <int>,
    "draws": <int>,
    "max_dtm_plies": <int>,
    "checkmates": <int>,
    "stalemates": <int>,
    "remaining_unknown": 0
}
```

- total_positions = white_wins + draws
- remaining_unknown must be 0 (all positions fully resolved)

### Module: /app/krk_tablebase.py

Must expose these functions:

```python
def generate():
    """Build the full KRK tablebase.
    Returns a dict with statistics.
    Must be called before lookup_fen()."""

def lookup_fen(fen: str) -> int:
    """Look up DTM for a FEN position.
    Returns: int >= 0 for positions won by white (DTM in plies),
             -1 for drawn positions.
    Raises ValueError for illegal/non-KRK positions.
    Auto-calls generate() if not yet generated."""
```

When run as a script (`python3 /app/krk_tablebase.py`), it must call `generate()` and write `/app/krk_results.json`.
