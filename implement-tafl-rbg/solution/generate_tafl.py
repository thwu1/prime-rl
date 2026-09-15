#!/usr/bin/env python3
"""
Generate the Tafl (Brandubh) game description in the RBG language.
Constructs the .rbg file programmatically from game-rule components.

"""

def build_tafl_rbg():
    """Build the complete Tafl RBG game description string."""

    # --- Header -----------------------------------------------------------
    header = "// Tafl (simplified 7x7 Brandubh variant)\n"

    # --- Players & pieces -------------------------------------------------
    players = "#players = defender(100), attacker(100)"
    pieces = "#pieces = e, d, k, a"
    variables = "#variables ="

    # --- Board (7x7 Brandubh starting position) ---------------------------
    #  Row 0-6, columns 0-6.  a=attacker, d=defender, k=king, e=empty
    rows = [
        "[e, e, e, a, e, e, e]",
        "[e, e, e, a, e, e, e]",
        "[e, e, e, d, e, e, e]",
        "[a, a, d, k, d, a, a]",
        "[e, e, e, d, e, e, e]",
        "[e, e, e, a, e, e, e]",
        "[e, e, e, a, e, e, e]",
    ]
    board = "#board = rectangle(up,down,left,right,\n"
    board += "\n".join("    " + r for r in rows) + ")"

    # --- Navigation -------------------------------------------------------
    any_square = "#anySquare = ((up* + down*)(left* + right*))"

    # --- Rook-style movement (slide through empty squares) ----------------
    rook_slide = "#rookSlide(dir) = (dir {e} (dir {e})*)"
    rook_move = (
        "#rookMove = ("
        "rookSlide(up) + rookSlide(down) + "
        "rookSlide(left) + rookSlide(right))"
    )

    # --- Custodial capture ------------------------------------------------
    # For a given direction: if the adjacent cell holds an opponent and the
    # cell beyond holds a friendly piece, remove the opponent.  Otherwise
    # the negation branch matches and nothing happens.
    capture_dir = "\n".join([
        "#captureDir(dir; backDir; oppPieces; myPieces) = (",
        "      {! dir {oppPieces} dir {myPieces}}",
        "    + dir {oppPieces} [e] dir {myPieces} backDir^2",
        "  )",
    ])

    capture_all = "\n".join([
        "#captureAll(oppPieces; myPieces) =",
        "    captureDir(right; left; oppPieces; myPieces)",
        "    captureDir(left; right; oppPieces; myPieces)",
        "    captureDir(up; down; oppPieces; myPieces)",
        "    captureDir(down; up; oppPieces; myPieces)",
    ])

    # --- Win / loss conditions --------------------------------------------
    king_escaped = (
        "#kingEscaped = anySquare {k} "
        "({! up} + {! down} + {! left} + {! right})"
    )
    king_captured = (
        "#kingCaptured = anySquare {k} "
        "{? up {a}} {? down {a}} {? left {a}} {? right {a}}"
    )

    check_end = "\n".join([
        "#checkEndGame = (",
        "      {? kingEscaped} [$ defender=100, attacker=0] ->> {}",
        "    + {? kingCaptured} [$ attacker=100, defender=0] ->> {}",
        "    + {! kingEscaped} {! kingCaptured}",
        "  )",
    ])

    # --- Turn structure ---------------------------------------------------
    defender_turn = "\n".join([
        "#defenderTurn =",
        "    ->defender anySquare (",
        "        {d} [e] rookMove ->> [d] captureAll(a; d,k)",
        "      + {k} [e] rookMove ->> [k] captureAll(a; d,k)",
        "    )",
        "    [$ defender=100, attacker=0]",
        "    checkEndGame",
    ])

    attacker_turn = "\n".join([
        "#attackerTurn =",
        "    ->attacker anySquare {a} [e] rookMove ->> [a] captureAll(d; a)",
        "    [$ attacker=100, defender=0]",
        "    checkEndGame",
    ])

    rules = "\n".join([
        "#rules = (",
        "    defenderTurn",
        "    attackerTurn",
        "  )*",
    ])

    # --- Assemble ---------------------------------------------------------
    sections = [
        header, players, pieces, variables, "", board, "",
        any_square, "", rook_slide, rook_move, "",
        capture_dir, "", capture_all, "",
        king_escaped, king_captured, "", check_end, "",
        defender_turn, "", attacker_turn, "",
        rules, "",
    ]
    return "\n".join(sections)


if __name__ == "__main__":
    rbg_content = build_tafl_rbg()
    with open("/app/tafl.rbg", "w") as f:
        f.write(rbg_content)
    print(f"Wrote {len(rbg_content)} bytes to /app/tafl.rbg")
