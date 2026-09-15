/*
 *
 * Kalah shared library — ctypes-callable API derived from the
 * reference C engine at /app/engine/kalah_engine.c.
 * Compile: gcc -shared -fPIC -O2 -o /app/libkalah.so kalah_lib.c
 */

#include <string.h>

#define MAX_PITS 8
#define MAX_BSZ (2 * MAX_PITS + 2)

static int board[MAX_BSZ];
static int n_pits, bsz, ss_idx, ns_idx;
static int cur_player;
static int captures_on;
static int game_over_flag;

void kalah_init(int np, int k, int cap) {
    n_pits = np;
    bsz = 2 * np + 2;
    ss_idx = np;
    ns_idx = 2 * np + 1;
    captures_on = cap;
    cur_player = 0;
    game_over_flag = 0;
    memset(board, 0, sizeof(board));
    for (int i = 0; i < np; i++) board[i] = k;
    for (int i = np + 1; i < 2 * np + 1; i++) board[i] = k;
}

void kalah_load(int np, int cap, int *brd, int brd_len, int player) {
    n_pits = np;
    bsz = 2 * np + 2;
    ss_idx = np;
    ns_idx = 2 * np + 1;
    captures_on = cap;
    cur_player = player;
    game_over_flag = 0;
    memset(board, 0, sizeof(board));
    for (int i = 0; i < bsz && i < brd_len; i++) board[i] = brd[i];
}

int kalah_play(int local_pit) {
    if (game_over_flag) return -1;
    int pit;
    if (cur_player == 0) {
        pit = local_pit;
        if (pit < 0 || pit >= n_pits) return -1;
    } else {
        pit = n_pits + 1 + local_pit;
        if (local_pit < 0 || local_pit >= n_pits) return -1;
    }
    if (board[pit] == 0) return -1;

    int seeds = board[pit];
    board[pit] = 0;
    int skip = (cur_player == 0) ? ns_idx : ss_idx;
    int c = pit;
    while (seeds > 0) {
        c = (c + 1) % bsz;
        if (c == skip) continue;
        board[c]++;
        seeds--;
    }
    int my_store = (cur_player == 0) ? ss_idx : ns_idx;
    int extra = (c == my_store);

    if (captures_on && !extra) {
        if (cur_player == 0 && c >= 0 && c < n_pits && board[c] == 1) {
            int opp = 2 * n_pits - c;
            if (board[opp] > 0) {
                board[ss_idx] += 1 + board[opp];
                board[c] = 0;
                board[opp] = 0;
            }
        } else if (cur_player == 1 && c >= n_pits + 1 && c <= 2 * n_pits
                   && board[c] == 1) {
            int opp = 2 * n_pits - c;
            if (board[opp] > 0) {
                board[ns_idx] += 1 + board[opp];
                board[c] = 0;
                board[opp] = 0;
            }
        }
    }

    /* Check game over */
    int se = 1, ne = 1;
    for (int i = 0; i < n_pits; i++)
        if (board[i] > 0) { se = 0; break; }
    for (int i = n_pits + 1; i < 2 * n_pits + 1; i++)
        if (board[i] > 0) { ne = 0; break; }
    if (se || ne) {
        for (int i = 0; i < n_pits; i++) {
            board[ss_idx] += board[i]; board[i] = 0;
        }
        for (int i = n_pits + 1; i < 2 * n_pits + 1; i++) {
            board[ns_idx] += board[i]; board[i] = 0;
        }
        game_over_flag = 1;
        return 2; /* game over */
    }
    if (!extra) cur_player = 1 - cur_player;
    return extra ? 1 : 0; /* 1=extra turn, 0=normal */
}

int kalah_get_score(void) {
    return board[ss_idx] - board[ns_idx];
}

int kalah_is_over(void) {
    return game_over_flag;
}
