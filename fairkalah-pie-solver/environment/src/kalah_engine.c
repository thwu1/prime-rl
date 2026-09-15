/*
 * kalah_engine.c - Fast Kalah state operations
 *
 * Implements standard Kalah rules for use as a shared library via ctypes.
 * Board layout: [S0..Sn-1, SS, N0..Nn-1, NS]
 * Sowing: counter-clockwise, skip opponent's store.
 * Standard rules include empty-pit captures.
 */

#include "kalah_engine.h"
#include <string.h>

void kalah_init(KalahState *s, int n, int seeds) {
    memset(s, 0, sizeof(KalahState));
    s->n = n;
    s->side = 0;
    for (int i = 0; i < n; i++) {
        s->board[i] = seeds;
        s->board[n + 1 + i] = seeds;
    }
}

void kalah_set_board(KalahState *s, int n, const int *board, int side) {
    memset(s, 0, sizeof(KalahState));
    s->n = n;
    s->side = side;
    int total = 2 * (n + 1);
    for (int i = 0; i < total; i++) {
        s->board[i] = board[i];
    }
}

void kalah_copy(KalahState *dst, const KalahState *src) {
    memcpy(dst, src, sizeof(KalahState));
}

int kalah_is_terminal(const KalahState *s) {
    int south_empty = 1, north_empty = 1;
    for (int i = 0; i < s->n; i++) {
        if (s->board[i] > 0) south_empty = 0;
        if (s->board[s->n + 1 + i] > 0) north_empty = 0;
    }
    return south_empty || north_empty;
}

int kalah_terminal_score(const KalahState *s) {
    int south = s->board[s->n];
    int north = s->board[2 * s->n + 1];
    for (int i = 0; i < s->n; i++) {
        south += s->board[i];
        north += s->board[s->n + 1 + i];
    }
    return south - north;
}

int kalah_make_move(KalahState *s, int pit) {
    int n = s->n;
    int stones = s->board[pit];
    s->board[pit] = 0;
    int total = 2 * (n + 1);
    int opp_store = (s->side == 0) ? (2 * n + 1) : n;
    int own_store = (s->side == 0) ? n : (2 * n + 1);

    int idx = pit;
    for (int i = 0; i < stones; i++) {
        idx = (idx + 1) % total;
        if (idx == opp_store) idx = (idx + 1) % total;
        s->board[idx]++;
    }

    /* Extra turn: last stone landed in own store */
    if (idx == own_store) return 1;

    /* Standard capture: last stone in empty own pit, opposite has stones */
    int is_own;
    if (s->side == 0) {
        is_own = (idx >= 0 && idx < n);
    } else {
        is_own = (idx >= n + 1 && idx <= 2 * n);
    }
    if (is_own && s->board[idx] == 1) {
        int opp = 2 * n - idx;
        if (s->board[opp] > 0) {
            s->board[own_store] += s->board[idx] + s->board[opp];
            s->board[idx] = 0;
            s->board[opp] = 0;
        }
    }

    s->side = 1 - s->side;
    return 0;
}

int kalah_legal_moves(const KalahState *s, int *moves) {
    int count = 0;
    if (s->side == 0) {
        for (int i = 0; i < s->n; i++) {
            if (s->board[i] > 0) moves[count++] = i;
        }
    } else {
        for (int i = s->n + 1; i <= 2 * s->n; i++) {
            if (s->board[i] > 0) moves[count++] = i;
        }
    }
    return count;
}
