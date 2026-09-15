package com.kelseyde.calvin.board;

/**
 * Chess piece types.  Ordinal values match NNUE feature indices.
 */
public enum Piece {
    PAWN,      // 0
    KNIGHT,    // 1
    BISHOP,    // 2
    ROOK,      // 3
    QUEEN,     // 4
    KING;      // 5

    public static final int COUNT = 6;

    /** Returns the ordinal (PAWN=0, KNIGHT=1, …, KING=5). */
    public int index() { return ordinal(); }

    /** FEN character for this piece (lowercase). */
    public String code() {
        return switch (this) {
            case PAWN   -> "p";
            case KNIGHT -> "n";
            case BISHOP -> "b";
            case ROOK   -> "r";
            case QUEEN  -> "q";
            case KING   -> "k";
        };
    }
}
