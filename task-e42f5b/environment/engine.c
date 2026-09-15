/*
 * FairKalah variant game library.
 * Compiled as shared library (.so) for agent to reverse-engineer,
 * and as CLI binary for trace generation during build.
 */

#include <string.h>

#define MAX_H 6
#define MAX_SZ (2 * MAX_H + 2)

void fk_init(int h, int s, int *board) {
    int sz = 2 * h + 2;
    memset(board, 0, sz * sizeof(int));
    for (int i = 0; i < h; i++) board[i] = s;
    for (int i = h + 1; i < 2 * h + 1; i++) board[i] = s;
}

int fk_play(const int *board, int side, int pit, int h, int *nb) {
    int sz = 2 * h + 2;
    int my_store  = (side == 0) ? h : sz - 1;
    int opp_store = (side == 0) ? sz - 1 : h;
    memcpy(nb, board, sz * sizeof(int));
    int seeds = nb[pit];
    nb[pit] = 0;
    int pos = pit;
    for (;;) {
        for (int i = 0; i < seeds; i++) {
            pos = (pos + 1) % sz;
            if (pos == opp_store)
                pos = (pos + 1) % sz;
            nb[pos]++;
        }
        if (pos == my_store) break;
        if (nb[pos] <= 1) break;
        seeds = nb[pos];
        nb[pos] = 0;
    }
    int south_empty = 1, north_empty = 1;
    for (int i = 0; i < h; i++)
        if (nb[i] > 0) { south_empty = 0; break; }
    for (int i = h + 1; i < 2 * h + 1; i++)
        if (nb[i] > 0) { north_empty = 0; break; }
    if (south_empty || north_empty) {
        for (int i = 0; i < h; i++) { nb[h] += nb[i]; nb[i] = 0; }
        for (int i = h + 1; i < 2 * h + 1; i++) { nb[sz - 1] += nb[i]; nb[i] = 0; }
        return -1;
    }
    return (pos == my_store) ? side : 1 - side;
}

int fk_legal(const int *board, int side, int h, int *moves) {
    int count = 0;
    if (side == 0) {
        for (int i = 0; i < h; i++)
            if (board[i] > 0) moves[count++] = i;
    } else {
        for (int i = h + 1; i < 2 * h + 1; i++)
            if (board[i] > 0) moves[count++] = i;
    }
    return count;
}

int fk_term(const int *board, int h) {
    int se = 1, ne = 1;
    for (int i = 0; i < h; i++)
        if (board[i] > 0) { se = 0; break; }
    for (int i = h + 1; i < 2 * h + 1; i++)
        if (board[i] > 0) { ne = 0; break; }
    return se || ne;
}

int fk_score(const int *board, int h) {
    return board[h] - board[2 * h + 1];
}

#ifdef CLI_BUILD
#include <stdio.h>
#include <stdlib.h>

static void parse_csv(const char *s, int *b, int n) {
    for (int i = 0; i < n; i++) {
        b[i] = atoi(s);
        while (*s && *s != ',') s++;
        if (*s == ',') s++;
    }
}

static void print_csv(const int *b, int sz) {
    for (int i = 0; i < sz; i++) {
        if (i) putchar(',');
        printf("%d", b[i]);
    }
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: play|moves|init\n");
        return 1;
    }
    if (strcmp(argv[1], "play") == 0 && argc == 6) {
        int h = atoi(argv[2]), side = atoi(argv[4]), pit = atoi(argv[5]);
        int sz = 2 * h + 2, b[MAX_SZ] = {0}, nb[MAX_SZ];
        parse_csv(argv[3], b, sz);
        int ns = fk_play(b, side, pit, h, nb);
        print_csv(nb, sz);
        printf(" %d\n", ns);
    } else if (strcmp(argv[1], "moves") == 0 && argc == 5) {
        int h = atoi(argv[2]), side = atoi(argv[4]);
        int sz = 2 * h + 2, b[MAX_SZ] = {0}, moves[MAX_H];
        parse_csv(argv[3], b, sz);
        int cnt = fk_legal(b, side, h, moves);
        for (int i = 0; i < cnt; i++) { if (i) putchar(' '); printf("%d", moves[i]); }
        putchar('\n');
    } else if (strcmp(argv[1], "init") == 0 && argc == 4) {
        int h = atoi(argv[2]), s = atoi(argv[3]);
        int sz = 2 * h + 2, b[MAX_SZ] = {0};
        fk_init(h, s, b);
        print_csv(b, sz);
        putchar('\n');
    }
    return 0;
}
#endif
