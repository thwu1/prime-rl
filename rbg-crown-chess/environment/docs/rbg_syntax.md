# RBG Language Reference

## Overview
RBG (Regular Boardgames) is a domain-specific language for describing finite, deterministic, perfect-information board games using regular-expression-like patterns. Game descriptions are compiled by `rbg2cpp` into optimized C++ game reasoners.

## File Structure
An RBG game file consists of macro definitions:

```
#players = name1(initialScore), name2(initialScore)
#pieces = piece1, piece2, ..., e
#variables = var1(maxBits), var2(maxBits)
#board = rectangle(up, down, left, right, layout)
#rules = expression
```

Plus user-defined macros:
```
#macroName(param1; param2) = expression
```

## Players
```
#players = white(100), black(100)
```
Declares players with initial scores. Scores range from 0 to the declared maximum.

## Pieces
```
#pieces = whitePawn, blackPawn, e
```
`e` or `empty` represents an unoccupied square. Piece names are single tokens (no spaces). A common pattern uses the `~` (tilde) operator in macros for color-parameterized pieces:

```
#myPieces(color) = color~Pawn, color~Knight, color~King
#pieces = myPieces(white), myPieces(black), e
```
Here `color~Pawn` with `color=white` expands to `whitePawn`.

## Variables
```
#variables = moveCount(100), kingMoved(1)
```
Integer variables with maximum value (stored as bits). `varName(N)` can hold values 0 to N. Modified with `[$ varName = expr]`.

## Board
```
#board = rectangle(up, down, left, right,
    [piece1, piece2, piece3]
    [piece4, piece5, piece6]
    [piece7, piece8, piece9])
```
Defines a rectangular board with named directions. Top-left is the first element. Rows go top to bottom. The direction names (up/down/left/right) are used in movement expressions.

## Expressions

### Movement
- `up`, `down`, `left`, `right` — Move the cursor one step in the named direction. Fails if the edge doesn't exist (board boundary).
- Multiple moves chain: `up left` means go up then go left (reaching the diagonal square).

### Operators
| Syntax | Meaning |
|--------|---------|
| `A B` | Sequence: do A, then do B |
| `A + B` | Choice: do A or do B (nondeterministic) |
| `A*` | Zero or more repetitions of A |
| `A^n` | Exactly n repetitions of A |
| `(A)` | Grouping |

### Checks (read-only, test current square)
| Syntax | Meaning |
|--------|---------|
| `{piece}` | Current square contains `piece` |
| `{piece1, piece2}` | Current square contains `piece1` OR `piece2` |
| `{? expr}` | Positive lookahead: `expr` CAN match from here |
| `{! expr}` | Negative lookahead: `expr` CANNOT match from here |
| `{$ var == val}` | Variable equals value |
| `{$ var < val}` | Variable less than value |

### Actions (modify state)
| Syntax | Meaning |
|--------|---------|
| `[piece]` | Set current square to `piece` |
| `[$ var = val]` | Set variable to value |
| `[$ var = var + 1]` | Increment variable |
| `[$ player = score]` | Set player's score |

### Turn Control
| Syntax | Meaning |
|--------|---------|
| `->player` | Designate whose turn it is (player move follows) |
| `->>` | Backtracking barrier: committed, cannot undo past this point |

### Macros
```
#name(param1; param2) = expression
```
Parameters are separated by `;`. Called as `name(arg1; arg2)`. Macros expand textually.

## Common Patterns

### Navigate to any square
```
#anySquare = (left* + right*)(up* + down*)
```
From any position, reaches every square on the board.

### Any adjacent square (8 directions)
```
#anyNeighborSquare = (left + right + up + down + (left + right)(up + down))
```

### Pick up a piece (remove from board)
```
#pickUpPiece(piece) = {piece} [e]
```
Checks the current square has `piece`, then sets it to empty.

### Sliding movement (bishop-like diagonal)
```
#diagonalLine = (
    (up left {e})* up left
  + (up right {e})* up right
  + (down left {e})* down left
  + (down right {e})* down right
)
```
Slides through empty squares, stopping at the first non-empty or board edge. The final square can be empty or occupied (checked separately).

### Sliding movement (rook-like orthogonal)
```
#parallelLine = (
    (up {e})* up
  + (down {e})* down
  + (right {e})* right
  + (left {e})* left
)
```

### Knight jump
```
#knightHop = (
    (up^2 + down^2)(left + right)
  + (left^2 + right^2)(up + down)
)
```
Reaches all 8 L-shaped destinations. Intermediate squares are traversed but not checked.

### Capture or move to empty
```
#captureAnyBy(capturingPiece; oppColor) = (
    {e}
  + {opponentPieces(oppColor)}
) [capturingPiece]
```
Checks destination is empty or has an opponent piece, then places the capturing piece.

### Standard piece move (pick up, move, place)
```
#standardMove(piece; movePattern; oppColor) =
    pickUpPiece(piece)
    movePattern
    captureAnyBy(piece; oppColor)
```

## Game Flow with `#rules`

```
#rules = [$ white=50] [$ black=50] (
    turn(white; black)
    turn(black; white)
)*
```

The `*` repeats the turn sequence. If a turn fails (no legal moves), the loop ends and scores are final.

## Compilation & Testing

```bash
# Compile .rbg to C++ reasoner
/opt/rbg/rbg2cpp/bin/rbg2cpp -o reasoner game.rbg

# Compile the reasoner
g++ -O3 -std=c++23 -c -o reasoner.o reasoner.cpp
g++ -O3 -std=c++23 -o perft_test reasoner.o /opt/rbg/rbg2cpp/test/perft.cpp
./perft_test 3  # Run perft at depth 3
```

Output includes `perft: <leaves_count>` — the number of game states at exactly depth N.
