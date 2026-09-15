Write a valid RBG (Regular Boardgames) game description for a 6x6 chess variant called "Crown" and save it to `/app/crown.rbg`. The RBG compiler at `/opt/rbg/rbg2cpp/bin/rbg2cpp` must compile it without errors, and the compiled reasoner must produce correct perft counts at depths 1-4. RBG syntax documentation is at `/app/docs/rbg_syntax.md`, example games at `/app/docs/examples/`, and a helper script at `/app/build_and_perft.sh`.

## Game Specification

**Board:** 6x6 rectangle. **Players:** white (first), black. White moves upward, black downward.

**Initial layout:**
```
Row 0: bChariot  bKnight  bGuard  bKing  bKnight  bChariot
Row 1: bSoldier  bSoldier bSoldier bSoldier bSoldier bSoldier
Row 2-3: empty
Row 4: wSoldier  wSoldier wSoldier wSoldier wSoldier wSoldier
Row 5: wChariot  wKnight  wGuard  wKing  wKnight  wChariot
```

**Pieces (5 types per color):**
- **Soldier** -- forward 1 to empty; captures diagonally forward 1 (opponent only). Promotes to Guard on reaching the far rank.
- **Knight** -- L-shaped jump (2+1 squares), leaps over intervening pieces. Captures by replacement.
- **Guard** -- diagonal slider, blocked by intervening pieces. Captures by replacement.
- **Chariot** -- orthogonal slider, blocked by intervening pieces. Captures by replacement.
- **King** -- 1 square in any of 8 directions. Captures by replacement.

**Win condition:** capturing the opponent's King wins (score 100 vs 0). No legal moves = draw (both 50). No castling, en passant, double pawn moves, or move-count limits.

## Verification

Your implementation must compile and produce perft counts matching the reference at `/tests/reference_game.py`.