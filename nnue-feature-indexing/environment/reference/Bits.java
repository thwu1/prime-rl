package com.kelseyde.calvin.board;

/**
 * Bit-manipulation utilities for square indexing.
 *
 * Squares use LERF (Little-Endian Rank-File) mapping:
 *   a1=0, b1=1, c1=2, d1=3, e1=4, f1=5, g1=6, h1=7,
 *   a2=8, b2=9, …, h8=63.
 */
public class Bits {

    /** Returns the index of the lowest set bit and removes it. */
    public static int next(long bb) { return Long.numberOfTrailingZeros(bb); }
    public static long pop(long bb) { return bb & (bb - 1); }

    public static class Square {
        public static final int COUNT = 64;

        /** Mirrors the rank (rank 1 ↔ 8, rank 2 ↔ 7, etc.). */
        public static int flipRank(int sq) { return sq ^ 56; }

        /** Mirrors the file (a ↔ h, b ↔ g, etc.). */
        public static int flipFile(int sq) { return sq ^ 7; }
    }

    public static class File {
        /** File index: 0 = a-file, 7 = h-file. */
        public static int of(int sq) { return sq & 7; }
    }

    public static class Rank {
        /** Rank index: 0 = rank 1, 7 = rank 8. */
        public static int of(int sq) { return sq >> 3; }
    }
}
