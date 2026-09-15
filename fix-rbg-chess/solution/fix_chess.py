#!/usr/bin/env python3
"""
Fix the bugs in chess_buggy.rbg by applying targeted string replacements.

The buggy file has three rule-encoding errors that cause incorrect perft counts.
Each fix restores the correct Chess rule semantics in the RBG DSL.
"""


def fix_chess_rbg(input_path: str, output_path: str) -> None:
    with open(input_path, "r") as f:
        content = f.read()

    # Fix 1: Knight hop — restore down^2
    # Buggy:   (up^2 + down)(left + right)
    # Correct: (up^2 + down^2)(left + right)
    # The knight moves in an L-shape: 2 squares in one direction + 1 in the
    # perpendicular. Using 'down' (1 square) instead of 'down^2' (2 squares)
    # breaks the L-shape for the downward direction. This also corrupts the
    # isAttackedBy check-detection macro which reuses knightHop.
    content = content.replace(
        "(up^2 + down)(left + right)",
        "(up^2 + down^2)(left + right)",
    )

    # Fix 2: Pawn capture direction — restore (left + right)
    # Buggy:   forward left {singleColorPieces(oppColor)}
    # Correct: forward (left + right) {singleColorPieces(oppColor)}
    # Pawns capture diagonally in both forward-left and forward-right directions.
    # Only allowing left-diagonal captures removes all right-diagonal pawn captures.
    content = content.replace(
        "forward left {singleColorPieces(oppColor)}",
        "forward (left + right) {singleColorPieces(oppColor)}",
    )

    # Fix 3: Pawn double push rank restriction — restore {! backward^2}
    # Buggy:   the double-push branch lacks the starting-rank guard
    # Correct: {! backward^2} before (forward {empty})^2
    # Pawns may only double-push from their starting rank. The '{! backward^2}'
    # pattern checks that the pawn cannot move 2 squares backward (i.e., it is
    # on the starting rank). Without this guard, any pawn can double-push from
    # any rank.
    content = content.replace(
        "      + (forward {empty})^2\n"
        "        [color~Pawn] // Promotion cannot occur",
        "      + {! backward^2}\n"
        "        (forward {empty})^2\n"
        "        [color~Pawn] // Promotion cannot occur",
    )

    with open(output_path, "w") as f:
        f.write(content)

    print(f"Fixed chess.rbg written to {output_path}")


if __name__ == "__main__":
    fix_chess_rbg("/app/chess_buggy.rbg", "/app/chess_fixed.rbg")
