#!/usr/bin/env python3
"""
Generate a complete English Draughts (8x8 American Checkers) game description
in the RBG domain-specific language.

Rules implemented:
- 8x8 board, 12 pieces per side on alternating dark squares
- Men move/capture diagonally forward only
- Kings move/capture in all 4 diagonal directions (one square)
- Mandatory captures: if any capture exists, non-capture moves are illegal
- Multi-jump sequences with mandatory continuation
- King promotion on reaching opposite back rank
- Promotion during capture sequence ends the turn immediately
- Black moves first
- Player with no legal moves loses (opponent scores 100)

Perft reference (initial position):
  depth 1 =       7
  depth 2 =      49
  depth 3 =     302
  depth 4 =   1,469
  depth 5 =   7,361
  depth 6 =  36,768
  depth 7 = 179,740
"""

import textwrap

RBG_SOURCE = textwrap.dedent("""\
    // English Draughts (8x8 American Checkers)
    // Men move/capture forward only. Kings move/capture all 4 diagonals.
    // Captures are mandatory. Multi-jump sequences must be completed.
    // Promotion during a capture sequence ends the turn immediately.

    #players = black(100), white(100)
    #pieces = e, b, w, B, W
    #variables =

    #board = rectangle(up,down,left,right,
       [e, b, e, b, e, b, e, b]
       [b, e, b, e, b, e, b, e]
       [e, b, e, b, e, b, e, b]
       [e, e, e, e, e, e, e, e]
       [e, e, e, e, e, e, e, e]
       [w, e, w, e, w, e, w, e]
       [e, w, e, w, e, w, e, w]
       [w, e, w, e, w, e, w, e])

    #anySquare = (left* + right*)(up* + down*)

    // -- Pure jump-availability checks (no state modification) --
    // Used inside negative/positive lookaheads to enforce mandatory captures.

    #canManJump(oppPcs; forward) =
        (forward left {oppPcs} forward left {e}
       + forward right {oppPcs} forward right {e})

    #canKingJump(oppPcs) =
        (up left {oppPcs} up left {e}
       + up right {oppPcs} up right {e}
       + down left {oppPcs} down left {e}
       + down right {oppPcs} down right {e})

    // Global check: can ANY of my pieces capture?
    #anyCapture(myMan; myKing; oppPcs; forward) =
        anySquare ({myMan} canManJump(oppPcs; forward) + {myKing} canKingJump(oppPcs))

    // -- Capture jump actions (remove captured piece from board) --

    #manJump(oppPcs; forward) =
        (forward left {oppPcs} [e] forward left
       + forward right {oppPcs} [e] forward right) {e}

    #kingJump(oppPcs) =
        (up left {oppPcs} [e] up left
       + up right {oppPcs} [e] up right
       + down left {oppPcs} [e] down left
       + down right {oppPcs} [e] down right) {e}

    // -- Capture sequences --
    // Man capture: pick up man, execute one or more jumps.
    // {? forward} inside the Kleene star prevents continuation past the back rank.
    // At the back rank ({! forward}), the man promotes and the turn ends.
    // Otherwise, {! canManJump} enforces mandatory jump continuation.
    #manCapture(myMan; oppPcs; forward; myKing) =
        {myMan} [e]
        manJump(oppPcs; forward)
        ({? forward} manJump(oppPcs; forward))*
        ({! forward} [myKing] + {? forward} {! canManJump(oppPcs; forward)} [myMan])

    // King capture: pick up king, execute one or more jumps.
    // {! canKingJump} ensures all continuation jumps are exhausted.
    #kingCapture(myKing; oppPcs) =
        {myKing} [e]
        kingJump(oppPcs)
        (kingJump(oppPcs))*
        {! canKingJump(oppPcs)}
        [myKing]

    // -- Simple (non-capture) moves --
    #manSimple(myMan; forward; myKing) =
        {myMan} [e]
        forward (left + right) {e}
        ({? forward} [myMan] + {! forward} [myKing])

    #kingSimple(myKing) =
        {myKing} [e]
        (up + down)(left + right) {e}
        [myKing]

    // -- Full turn --
    // Capture moves are always legal when they exist.
    // Non-capture moves are guarded by {! anyCapture(...)}: only legal
    // when NO piece of the current player can capture.
    #turn(me; myMan; myKing; opp; oppMan; oppKing; forward) =
        ->me (
            anySquare (
                manCapture(myMan; oppMan,oppKing; forward; myKing)
              + kingCapture(myKing; oppMan,oppKing)
            )
          + {! anyCapture(myMan; myKing; oppMan,oppKing; forward)}
            anySquare (
                manSimple(myMan; forward; myKing)
              + kingSimple(myKing)
            )
        )
        ->> [$ me=100] [$ opp=0]

    #rules = (
        turn(black; b; B; white; w; W; down)
        turn(white; w; W; black; b; B; up)
      )*
""")


def main():
    output_path = "/app/draughts.rbg"
    with open(output_path, "w") as f:
        f.write(RBG_SOURCE)
    print(f"Wrote English Draughts RBG description to {output_path}")


if __name__ == "__main__":
    main()
