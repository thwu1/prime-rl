/*
 *
 * Interactive Kalah (Mancala) game engine.
 * Accepts commands via stdin, responds via stdout.
 * Supports standard and no-capture (FairKalah) variants.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_PITS 8
#define MAX_BSZ (2 * MAX_PITS + 2)
#define MAX_HIST 4000

static int board[MAX_BSZ];
static int n_pits, bsz, ss_idx, ns_idx;
static int cur_player;
static int captures_on;
static int game_over;
static int initialized;

static int hist_board[MAX_HIST][MAX_BSZ];
static int hist_player[MAX_HIST];
static int hist_gameover[MAX_HIST];
static int hist_n;

static void push_hist(void) {
    if (hist_n >= MAX_HIST) return;
    for (int i = 0; i < bsz; i++) hist_board[hist_n][i] = board[i];
    hist_player[hist_n] = cur_player;
    hist_gameover[hist_n] = game_over;
    hist_n++;
}

static int pop_hist(void) {
    if (hist_n <= 0) return 0;
    hist_n--;
    for (int i = 0; i < bsz; i++) board[i] = hist_board[hist_n][i];
    cur_player = hist_player[hist_n];
    game_over = hist_gameover[hist_n];
    return 1;
}

static void do_init(int np, int k, int cap) {
    n_pits = np;
    bsz = 2 * np + 2;
    ss_idx = np;
    ns_idx = 2 * np + 1;
    captures_on = cap;
    cur_player = 0;
    game_over = 0;
    initialized = 1;
    hist_n = 0;
    for (int i = 0; i < np; i++) board[i] = k;
    board[ss_idx] = 0;
    for (int i = np + 1; i < 2 * np + 1; i++) board[i] = k;
    board[ns_idx] = 0;
}

static void do_load(int np, int cap, int *brd, int player) {
    n_pits = np;
    bsz = 2 * np + 2;
    ss_idx = np;
    ns_idx = 2 * np + 1;
    captures_on = cap;
    cur_player = player;
    game_over = 0;
    initialized = 1;
    hist_n = 0;
    for (int i = 0; i < bsz; i++) board[i] = brd[i];
}

static int check_gameover(void) {
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
        game_over = 1;
        return 1;
    }
    return 0;
}

static int do_play(int local_pit) {
    if (game_over) { printf("ERROR game is over\n"); return -1; }
    int pit;
    if (cur_player == 0) {
        pit = local_pit;
        if (pit < 0 || pit >= n_pits) {
            printf("ERROR invalid pit index\n"); return -1;
        }
    } else {
        pit = n_pits + 1 + local_pit;
        if (local_pit < 0 || local_pit >= n_pits) {
            printf("ERROR invalid pit index\n"); return -1;
        }
    }
    if (board[pit] == 0) { printf("ERROR pit is empty\n"); return -1; }

    push_hist();
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
    if (check_gameover()) return 0;
    if (!extra) cur_player = 1 - cur_player;
    return extra ? 1 : 0;
}

int main(void) {
    char line[2048];
    setbuf(stdout, NULL);
    initialized = 0;
    n_pits = 0;
    bsz = 0;
    printf("KALAH ENGINE v1.0 READY\n");

    while (fgets(line, sizeof(line), stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        if (strlen(line) == 0) continue;

        if (strncmp(line, "init ", 5) == 0) {
            int np, k;
            char capstr[32] = {0};
            if (sscanf(line + 5, "%d %d %31s", &np, &k, capstr) == 3) {
                if (np < 1 || np > MAX_PITS || k < 0) {
                    printf("ERROR invalid parameters\n");
                } else {
                    int cap = (strcmp(capstr, "standard") == 0) ? 1 : 0;
                    do_init(np, k, cap);
                    printf("OK\n");
                }
            } else {
                printf("ERROR usage: init <pits> <seeds> standard|nocapture\n");
            }
        }
        else if (strncmp(line, "load ", 5) == 0) {
            char buf[2048];
            strncpy(buf, line + 5, sizeof(buf) - 1);
            buf[sizeof(buf) - 1] = 0;
            char *toks[60];
            int nt = 0;
            char *tk = strtok(buf, " ");
            while (tk && nt < 60) { toks[nt++] = tk; tk = strtok(NULL, " "); }
            if (nt < 3) { printf("ERROR load needs more args\n"); continue; }
            int np = atoi(toks[0]);
            if (np < 1 || np > MAX_PITS) {
                printf("ERROR invalid pits\n"); continue;
            }
            int expected = 2 + 2 * np + 2 + 1;
            if (nt != expected) {
                printf("ERROR expected %d args got %d\n", expected, nt);
                continue;
            }
            int cap = (strcmp(toks[1], "standard") == 0) ? 1 : 0;
            int brd[MAX_BSZ];
            int bsz_l = 2 * np + 2;
            for (int i = 0; i < bsz_l; i++) brd[i] = atoi(toks[2 + i]);
            int player = atoi(toks[2 + bsz_l]);
            if (player < 0 || player > 1) {
                printf("ERROR player must be 0 or 1\n"); continue;
            }
            do_load(np, cap, brd, player);
            printf("OK\n");
        }
        else if (strcmp(line, "show") == 0) {
            if (!initialized) { printf("ERROR not initialized\n"); continue; }
            printf("BOARD");
            for (int i = 0; i < bsz; i++) printf(" %d", board[i]);
            printf(" PLAYER %d OVER %d\n", cur_player, game_over);
        }
        else if (strcmp(line, "moves") == 0) {
            if (!initialized) { printf("ERROR not initialized\n"); continue; }
            if (game_over) { printf("MOVES\n"); continue; }
            printf("MOVES");
            if (cur_player == 0) {
                for (int i = 0; i < n_pits; i++)
                    if (board[i] > 0) printf(" %d", i);
            } else {
                for (int i = n_pits + 1; i < 2 * n_pits + 1; i++)
                    if (board[i] > 0) printf(" %d", i - (n_pits + 1));
            }
            printf("\n");
        }
        else if (strncmp(line, "play ", 5) == 0) {
            if (!initialized) { printf("ERROR not initialized\n"); continue; }
            int pit;
            if (sscanf(line + 5, "%d", &pit) == 1) {
                int r = do_play(pit);
                if (r >= 0)
                    printf("OK extra=%d over=%d\n", r, game_over);
            } else {
                printf("ERROR usage: play <pit>\n");
            }
        }
        else if (strcmp(line, "undo") == 0) {
            if (!initialized) { printf("ERROR not initialized\n"); continue; }
            if (pop_hist()) printf("OK\n");
            else printf("ERROR no history\n");
        }
        else if (strcmp(line, "state") == 0) {
            if (!initialized) { printf("ERROR not initialized\n"); continue; }
            printf("{\"south_pits\":[");
            for (int i = 0; i < n_pits; i++) {
                if (i > 0) printf(",");
                printf("%d", board[i]);
            }
            printf("],\"south_store\":%d,\"north_pits\":[", board[ss_idx]);
            for (int i = n_pits + 1; i < 2 * n_pits + 1; i++) {
                if (i > n_pits + 1) printf(",");
                printf("%d", board[i]);
            }
            printf("],\"north_store\":%d,\"player\":%d,\"game_over\":%s}\n",
                   board[ns_idx], cur_player,
                   game_over ? "true" : "false");
        }
        else if (strcmp(line, "value") == 0) {
            if (!initialized) { printf("ERROR not initialized\n"); continue; }
            printf("VALUE %d\n", board[ss_idx] - board[ns_idx]);
        }
        else if (strcmp(line, "status") == 0) {
            if (!initialized) { printf("ERROR not initialized\n"); continue; }
            printf("STATUS over=%d south_store=%d north_store=%d diff=%d\n",
                   game_over, board[ss_idx], board[ns_idx],
                   board[ss_idx] - board[ns_idx]);
        }
        else if (strcmp(line, "help") == 0) {
            printf("COMMANDS: init load show moves play undo state value status help quit\n");
        }
        else if (strcmp(line, "quit") == 0 || strcmp(line, "exit") == 0) {
            printf("BYE\n");
            break;
        }
        else {
            printf("ERROR unknown command: %s\n", line);
        }
    }
    return 0;
}
