# NNUE Feature Index Computation — Specification

## Overview

NNUE (Efficiently Updatable Neural Network) is an evaluation architecture used in modern chess engines. The network uses a **perspective-based** input scheme: each side (white and black) maintains its own set of active features based on the current board state. Features are indexed by piece type, piece color (relative to the perspective), and square (relative to the perspective), with additional transforms based on the king's position.

This document specifies the complete feature index computation pipeline.

## Square Numbering (LERF)

Squares use Little-Endian Rank-File mapping:

```
a1=0,  b1=1,  c1=2,  d1=3,  e1=4,  f1=5,  g1=6,  h1=7
a2=8,  b2=9,  c2=10, d2=11, e2=12, f2=13, g2=14, h2=15
...
a8=56, b8=57, c8=58, d8=59, e8=60, f8=61, g8=62, h8=63
```

Helper operations:
- `file_of(sq) = sq & 7`  (0=a-file, 7=h-file)
- `rank_of(sq) = sq >> 3`  (0=rank 1, 7=rank 8)
- `flip_rank(sq) = sq ^ 56`  (mirrors rank 1↔8, 2↔7, etc.)
- `flip_file(sq) = sq ^ 7`   (mirrors a↔h, b↔g, etc.)

## Piece Type Indices

| Piece  | Index |
|--------|-------|
| Pawn   | 0     |
| Knight | 1     |
| Bishop | 2     |
| Rook   | 3     |
| Queen  | 4     |
| King   | 5     |

## Architecture Parameters

- **Input size**: 768 features = 2 colors × 6 piece types × 64 squares
- **Horizontal mirroring**: enabled
- **Input bucket map** (64 entries, indexed by perspective-adjusted king square):

```
 0, 1, 2, 3, 3, 2, 1, 0,    (rank 1 from perspective)
 4, 4, 5, 5, 5, 5, 4, 4,    (rank 2)
 6, 6, 6, 6, 6, 6, 6, 6,    (rank 3)
 6, 6, 6, 6, 6, 6, 6, 6,    (rank 4)
 6, 6, 6, 6, 6, 6, 6, 6,    (rank 5)
 7, 7, 7, 7, 7, 7, 7, 7,    (rank 6)
 7, 7, 7, 7, 7, 7, 7, 7,    (rank 7)
 7, 7, 7, 7, 7, 7, 7, 7     (rank 8)
```

- **Number of buckets**: 8

## King Bucket Computation

Given a king on square `king_sq` for a given `white_perspective`:

1. Adjust the square for perspective:
   - If `white_perspective`: `adj_sq = king_sq`
   - If black perspective: `adj_sq = flip_rank(king_sq)`
2. Look up: `bucket = INPUT_BUCKETS[adj_sq]`

## Horizontal Mirror Check

Mirroring is determined by the perspective's own king position:

1. Compute `adj_sq` as above (perspective-adjusted king square)
2. `mirror = (file_of(adj_sq) > 3)`

When mirroring is active, all feature square indices are flipped horizontally.

## Feature Index Formula

For a piece with type `piece_type` (0–5) and color `piece_white` (boolean) on square `sq` (0–63), from a given `white_perspective`, with the perspective's king on `king_sq`:

1. **Perspective-adjust the piece square**:
   - If `white_perspective`: `mapped_sq = sq`
   - If black perspective: `mapped_sq = flip_rank(sq)`

2. **Apply horizontal mirror** (based on the perspective's king):
   - Compute `king_adj = king_sq` if white perspective, else `flip_rank(king_sq)`
   - If `file_of(king_adj) > 3`: `mapped_sq = flip_file(mapped_sq)`

3. **Determine relative color**:
   - If `piece_white == white_perspective`: `color_offset = 0` (friendly piece)
   - Otherwise: `color_offset = 1` (enemy piece)

4. **Compute index**:
   ```
   feature_index = color_offset × 384 + piece_type × 64 + mapped_sq
   ```

Result range: [0, 767].

## Active Features

For a given position and perspective:

1. Find the king square for that perspective's color
2. Compute the king bucket
3. For every piece on the board, compute its feature index from this perspective
4. Return `(bucket, sorted_feature_list)`

## Full Refresh Detection

A full accumulator refresh is needed for a given perspective when:
- The piece being moved is the king belonging to that perspective, **AND**
- Either the king's bucket changes, or the mirror state changes

For castling moves, the king's destination is the standard castling square (g-file for kingside, c-file for queenside), regardless of the UCI `to` square.

Non-king moves **never** require a refresh for either perspective.

## Feature Delta (Incremental Update)

When no refresh is needed, compute the feature changes using the perspective's **current** (pre-move) king square:

- **Standard move**: sub piece from source, add piece to destination
- **Capture**: sub piece from source, sub captured piece from destination, add moving piece to destination
- **En passant**: sub moving pawn from source, add moving pawn to destination, sub captured pawn from its square (one rank behind the destination, toward the capturing side)
- **Castling**: sub king from source, add king to destination, sub rook from source, add rook to destination
- **Promotion**: sub pawn from source, add promoted piece to destination; if capture, also sub captured piece

Return `(sorted_adds, sorted_subs)` as lists of feature indices.

## Move Application

UCI moves are strings like `"e2e4"`, `"e1g1"`, `"e7e8q"`. Apply them as follows:

- **Castling detection**: a king moving ≥ 2 files. In standard chess:
  - Kingside: king → g-file, rook from h-file → f-file (same rank)
  - Queenside: king → c-file, rook from a-file → d-file (same rank)
- **En passant detection**: a pawn moving diagonally to the current EP square. The captured pawn is on the destination file, one rank behind the destination (from the capturer's perspective).
- **Promotion**: indicated by a 5th character in the UCI string (`q`, `r`, `b`, or `n`).
- **State updates after each move**:
  - Clear EP square; set new EP square only if a pawn moved two ranks
  - Update castling rights when king or rook moves or is captured
  - Reset halfmove clock on pawn moves and captures; otherwise increment
  - Increment fullmove counter after black's move
  - Toggle side to move

## Required Function Signatures

```python
def parse_fen(fen: str) -> Position
def active_features(pos: Position, white_perspective: bool) -> tuple[int, list[int]]
def make_move(pos: Position, uci_move: str) -> Position
def needs_refresh(pos: Position, uci_move: str, white_perspective: bool) -> bool
def feature_delta(pos: Position, uci_move: str, white_perspective: bool) -> tuple[list[int], list[int]]
def feature_index(piece_type: int, piece_white: bool, sq: int, white_perspective: bool, king_sq: int) -> int
def king_bucket(king_sq: int, white_perspective: bool) -> int
```

The `Position` type is implementation-defined but must support all required operations.
