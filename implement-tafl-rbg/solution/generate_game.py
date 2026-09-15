#!/usr/bin/env python3
"""
Generate the Isolation Breakthrough game description in the RBG language.
Combines Breakthrough movement with custodial capture of isolated pieces.

"""


def build_rbg():
    """Build the complete Isolation Breakthrough RBG game description."""

    lines = []

    # Header
    lines.append("// Isolation Breakthrough (6x6)")
    lines.append("// Breakthrough variant with custodial capture of isolated pieces.")
    lines.append("")

    # Players, pieces, variables
    lines.append("#players = white(100), black(100)")
    lines.append("#pieces = e, w, b")
    lines.append("#variables =")

    # Board (6x6, white bottom 2 rows, black top 2 rows)
    lines.append("#board = rectangle(up,down,left,right,")
    lines.append("         [b, b, b, b, b, b]")
    lines.append("         [b, b, b, b, b, b]")
    lines.append("         [e, e, e, e, e, e]")
    lines.append("         [e, e, e, e, e, e]")
    lines.append("         [w, w, w, w, w, w]")
    lines.append("         [w, w, w, w, w, w])")
    lines.append("")

    # Navigation helper
    lines.append("#anySquare = ((up* + down*)(left* + right*))")
    lines.append("")

    # Isolation check: a piece has no orthogonal neighbor of the same color
    lines.append(
        "#isIsolated(pawn) = {! (up + down + left + right) {pawn}}"
    )
    lines.append("")

    # Capturable check: opponent piece is isolated AND sandwiched
    lines.append("#isCapturable(oppPawn; myPawn) = (")
    lines.append("    {oppPawn}")
    lines.append("    isIsolated(oppPawn)")
    lines.append("    (")
    lines.append("        {? left {myPawn}} {? right {myPawn}}")
    lines.append("      + {? up {myPawn}} {? down {myPawn}}")
    lines.append("    )")
    lines.append("  )")
    lines.append("")

    # Iterative capture resolution
    lines.append("#resolveCaptures(oppPawn; myPawn) = (")
    lines.append("    (")
    lines.append("      anySquare isCapturable(oppPawn; myPawn) [e] ->>")
    lines.append("    )*")
    lines.append("    {! anySquare isCapturable(oppPawn; myPawn)}")
    lines.append("  )")
    lines.append("")

    # Back-row check
    lines.append(
        "#reachedBackRow(myPawn; forward) = anySquare {myPawn} {! forward}"
    )
    lines.append("")

    # Turn structure
    lines.append(
        "#turn(me; myPawn; opp; oppPawn; forward) ="
    )
    lines.append(
        "    ->me anySquare {myPawn}"
    )
    lines.append(
        "    [e] forward ({e} + (left+right) {e,oppPawn})"
    )
    lines.append("    [myPawn]")
    lines.append("    [$ me=100] [$ opp=0]")
    lines.append("    ->>")
    lines.append("    resolveCaptures(oppPawn; myPawn)")
    lines.append("    (")
    lines.append("        {? reachedBackRow(myPawn; forward)} ->> {}")
    lines.append("      + {! anySquare {oppPawn}} ->> {}")
    lines.append(
        "      + {! reachedBackRow(myPawn; forward)} {? anySquare {oppPawn}}"
    )
    lines.append("    )")
    lines.append("")

    # Rules
    lines.append("#rules = (")
    lines.append("      turn(white; w; black; b; up)")
    lines.append("      turn(black; b; white; w; down)")
    lines.append("    )*")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    content = build_rbg()
    with open("/app/isolation_breakthrough.rbg", "w") as f:
        f.write(content)
    print(f"Wrote {len(content)} bytes to /app/isolation_breakthrough.rbg")
