/*
 * perft960.h - Public API for the Chess960 perft shared library
 *
 * Declares Board, Stats structs and parse_fen/perft function prototypes
 * for use by external callers (ctypes, other C programs, etc.)
 */


#ifndef PERFT960_H
#define PERFT960_H

/* Piece types */
enum { EMPTY_SQ, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING };

/* Castling right bits */
#define CWK 1
#define CWQ 2
#define CBK 4
#define CBQ 8

/* Board state */
typedef struct {
    int sq[64];        /* positive = white, negative = black, abs = piece type */
    int side;          /* +1 white, -1 black */
    int castle;        /* castling rights bitmask */
    int ep;            /* en passant target square, -1 if none */
    int king_sq[2];    /* king positions: [0]=white, [1]=black */
    int castle_rook[4]; /* initial rook squares: [0]=WK, [1]=WQ, [2]=BK, [3]=BQ */
} Board;

/* Extended perft statistics */
typedef struct {
    long long nodes;
    long long captures;
    long long ep;
    long long castles;
    long long promotions;
    long long checks;
    long long checkmates;
} Stats;

/* Parse a FEN string into a Board. Supports both standard KQkq and
 * X-FEN/Shredder-FEN castling notation (A-H, a-h file letters). */
void parse_fen(Board *b, const char *fen);

/* Compute perft with extended statistics. Board is modified during
 * traversal but restored to original state on return. Stats are
 * accumulated (caller should zero-initialize before first call). */
void perft(Board *b, int depth, Stats *st);

#endif /* PERFT960_H */
