/*
 * kalah_engine.h - Kalah state operations header (with FairKalah support)
 */

#ifndef KALAH_ENGINE_H
#define KALAH_ENGINE_H

#define MAX_PITS 8
#define MAX_BOARD_SIZE (2 * (MAX_PITS + 1))

typedef struct {
    int board[MAX_BOARD_SIZE];  /* 18 ints */
    int n;                      /* pits per side */
    int side;                   /* 0 = south, 1 = north */
} KalahState;

void kalah_init(KalahState *s, int n, int seeds);
void kalah_set_board(KalahState *s, int n, const int *board, int side);
void kalah_copy(KalahState *dst, const KalahState *src);
int kalah_is_terminal(const KalahState *s);
int kalah_terminal_score(const KalahState *s);

/*
 * Execute a sowing move from the given pit index.
 * captures: 1 for standard rules (empty-pit captures), 0 for FairKalah (no captures).
 * Returns 1 if the current player gets an extra turn, 0 otherwise.
 */
int kalah_make_move(KalahState *s, int pit, int captures);

/* Fill moves[] with legal pit indices; return count. */
int kalah_legal_moves(const KalahState *s, int *moves);

#endif
