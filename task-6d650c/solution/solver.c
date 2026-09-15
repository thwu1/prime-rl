/*
 * Optimal 15-puzzle solver using IDA* with 5-5-5 disjoint pattern databases.
 *
 *
 * Algorithm:
 *   1. Build three pattern databases (tiles {1..5}, {6..10}, {11..15}) via
 *      reverse 0-1 BFS from goal states. Each PDB maps (blank_pos, tile_positions)
 *      to the minimum number of tracked-tile moves needed to place those tiles
 *      in their goal positions.
 *   2. Use IDA* with the sum of the three PDB lookups as heuristic (admissible
 *      and consistent due to disjoint additive property).
 *
 * Compile: gcc -O2 -o solver solver.c
 * Run:     ./solver < input.txt
 *   Input format: first line = count, then count lines of 16 tiles each.
 *   Output: one line per puzzle: "length M1 M2 ..." where Mi in {U,D,L,R}.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Board dimensions */
#define N       4
#define NN      16

/* P(16,6) = 16*15*14*13*12*11 -- number of entries per pattern database */
#define PDB_SZ  5765760

/* Maximum solution depth (God's number for 15-puzzle is 80) */
#define MAX_SOL 85

/* Sentinel for "no solution at this threshold" */
#define INF     9999

/* ---- Tile groups for 5-5-5 partition ---- */
static const int groups[3][5] = {
    {1, 2, 3, 4, 5},
    {6, 7, 8, 9, 10},
    {11, 12, 13, 14, 15}
};

/* ---- Pattern databases (one per group) ---- */
static unsigned char *pdb[3];

/* ---- Direction tables ---- */
/*  U=0  D=1  L=2  R=3 */
static const int dr[]   = {-1, 1,  0, 0};
static const int dc[]   = { 0, 0, -1, 1};
static const char dch[] = {'U','D','L','R'};
static const int opp[]  = { 1, 0,  3, 2};

/* Lehmer-code multipliers: emul[i] = product of (16-i-1) down to (16-6+1)
 *   emul[0]=15*14*13*12*11=360360   emul[1]=14*13*12*11=24024
 *   emul[2]=13*12*11=1716           emul[3]=12*11=132
 *   emul[4]=11                      emul[5]=1                   */
static const int emul[] = {360360, 24024, 1716, 132, 11, 1};

/* ---- Board state (global, modified in-place during search) ---- */
static int board[NN];   /* board[pos] = tile */
static int tpos[NN];    /* tpos[tile] = pos  (tpos[0] = blank position) */
static int blank;       /* = tpos[0] */

/* ---- IDA* state ---- */
static int sol[MAX_SOL]; /* solution moves (direction indices) */
static int sol_len;
static int threshold;
static int found;

/* ===================================================================
 *  Lehmer-code encoder: maps 6 distinct values from {0..15} to [0,PDB_SZ)
 * =================================================================== */
static inline int encode6(int p0, int p1, int p2, int p3, int p4, int p5)
{
    unsigned used = 0;
    int idx = 0, v, below;

    v = p0; below = __builtin_popcount(((1u << v) - 1) & ~used);
    idx += below * emul[0]; used |= 1u << v;

    v = p1; below = __builtin_popcount(((1u << v) - 1) & ~used);
    idx += below * emul[1]; used |= 1u << v;

    v = p2; below = __builtin_popcount(((1u << v) - 1) & ~used);
    idx += below * emul[2]; used |= 1u << v;

    v = p3; below = __builtin_popcount(((1u << v) - 1) & ~used);
    idx += below * emul[3]; used |= 1u << v;

    v = p4; below = __builtin_popcount(((1u << v) - 1) & ~used);
    idx += below * emul[4]; used |= 1u << v;

    v = p5; below = __builtin_popcount(((1u << v) - 1) & ~used);
    idx += below * emul[5];

    return idx;
}

/* ===================================================================
 *  Heuristic: sum of 3 PDB lookups
 * =================================================================== */
static inline int heuristic(void)
{
    int h = 0, idx;
    /* Group 0: tiles 1,2,3,4,5 */
    idx = encode6(tpos[0], tpos[1], tpos[2], tpos[3], tpos[4], tpos[5]);
    h += pdb[0][idx];
    /* Group 1: tiles 6,7,8,9,10 */
    idx = encode6(tpos[0], tpos[6], tpos[7], tpos[8], tpos[9], tpos[10]);
    h += pdb[1][idx];
    /* Group 2: tiles 11,12,13,14,15 */
    idx = encode6(tpos[0], tpos[11], tpos[12], tpos[13], tpos[14], tpos[15]);
    h += pdb[2][idx];
    return h;
}

/* ===================================================================
 *  BFS state for PDB construction (6 bytes, packed)
 * =================================================================== */
typedef struct { unsigned char p[6]; } BState;

/* ===================================================================
 *  Build pattern database for group g using 0-1 BFS.
 *
 *  The BFS starts from goal states (tiles at goal positions, blank at
 *  any non-tile position) and expands outward.  Moves that displace a
 *  tracked tile have cost 1; moves through wildcards (non-tracked tiles)
 *  have cost 0.  A two-queue approach handles the 0-1 weights.
 * =================================================================== */
static void build_pdb(int g)
{
    int i, d, b, bp, br, bc, nr, nc, np, ti;
    const int *gr = groups[g];
    int gp[5]; /* goal positions for the 5 tiles in this group */

    pdb[g] = (unsigned char *)malloc(PDB_SZ);
    if (!pdb[g]) { fprintf(stderr, "malloc PDB failed\n"); exit(1); }
    memset(pdb[g], 255, PDB_SZ);

    for (i = 0; i < 5; i++) gp[i] = gr[i]; /* goal pos = tile number */

    int cap = PDB_SZ + 256;
    BState *cur = (BState *)malloc(cap * sizeof(BState));
    BState *nxt = (BState *)malloc(cap * sizeof(BState));
    if (!cur || !nxt) { fprintf(stderr, "malloc queue failed\n"); exit(1); }
    int ch = 0, ct = 0, nt = 0;

    /* Seed: tiles at goal positions, blank at each valid (non-tile) position */
    for (b = 0; b < 16; b++) {
        int ok = 1;
        for (i = 0; i < 5; i++) if (b == gp[i]) { ok = 0; break; }
        if (!ok) continue;
        int idx = encode6(b, gp[0], gp[1], gp[2], gp[3], gp[4]);
        if (pdb[g][idx] != 255) continue;
        pdb[g][idx] = 0;
        BState s;
        s.p[0] = (unsigned char)b;
        for (i = 0; i < 5; i++) s.p[i+1] = (unsigned char)gp[i];
        cur[ct++] = s;
    }

    /* BFS loop: cur = cost-c states, nxt = cost-(c+1) states */
    while (ch < ct) {
        /* Process cur (including new 0-cost entries appended during this pass) */
        while (ch < ct) {
            BState s = cur[ch++];
            bp = s.p[0];
            br = bp / N; bc = bp % N;
            int idx0 = encode6(s.p[0], s.p[1], s.p[2], s.p[3], s.p[4], s.p[5]);
            unsigned char cost = pdb[g][idx0];

            for (d = 0; d < 4; d++) {
                nr = br + dr[d]; nc = bc + dc[d];
                if (nr < 0 || nr >= N || nc < 0 || nc >= N) continue;
                np = nr * N + nc;

                /* Is np occupied by a tracked tile? */
                ti = -1;
                for (i = 0; i < 5; i++)
                    if (s.p[i+1] == np) { ti = i; break; }

                BState ns = s;
                ns.p[0] = (unsigned char)np;
                unsigned char nc2;
                if (ti >= 0) {
                    ns.p[ti+1] = (unsigned char)bp;
                    nc2 = cost + 1;
                } else {
                    nc2 = cost;
                }

                int nidx = encode6(ns.p[0], ns.p[1], ns.p[2], ns.p[3],
                                   ns.p[4], ns.p[5]);
                if (pdb[g][nidx] <= nc2) continue;
                pdb[g][nidx] = nc2;

                if (ti >= 0) {
                    nxt[nt++] = ns;   /* cost + 1  -> next level */
                } else {
                    cur[ct++] = ns;   /* cost + 0  -> same level */
                }
            }
        }
        /* Swap queues: nxt becomes cur for the next cost level */
        BState *tmp = cur; cur = nxt; nxt = tmp;
        ch = 0; ct = nt; nt = 0;
    }

    free(cur);
    free(nxt);

    fprintf(stderr, "PDB group %d built\n", g);
}

/* ===================================================================
 *  IDA* depth-first search
 * =================================================================== */
static int dfs(int g, int last_d)
{
    int h = heuristic();
    int f = g + h;
    if (f > threshold) return f;
    if (h == 0) { sol_len = g; found = 1; return -1; }

    int min_f = INF;
    int br = blank / N, bc = blank % N;

    for (int d = 0; d < 4; d++) {
        if (last_d >= 0 && d == opp[last_d]) continue;
        int nr = br + dr[d], nc = bc + dc[d];
        if (nr < 0 || nr >= N || nc < 0 || nc >= N) continue;
        int np = nr * N + nc;

        /* Make move: swap blank with tile at np */
        int tile = board[np];
        board[blank] = tile; board[np] = 0;
        tpos[tile] = blank;  tpos[0] = np;
        int ob = blank; blank = np;
        sol[g] = d;

        int r = dfs(g + 1, d);
        if (found) return -1;
        if (r < min_f) min_f = r;

        /* Undo move */
        blank = ob;
        board[np] = tile; board[ob] = 0;
        tpos[tile] = np;   tpos[0] = ob;
    }

    return min_f;
}

static void solve_puzzle(void)
{
    int h = heuristic();
    threshold = h;
    found = 0;
    sol_len = 0;

    if (h == 0) return;   /* already at goal */

    while (!found) {
        int r = dfs(0, -1);
        if (found) break;
        if (r >= INF) {
            fprintf(stderr, "ERROR: no solution found\n");
            break;
        }
        threshold = r;
    }
}

/* ===================================================================
 *  Main: build PDBs, read puzzles, solve, write results to stdout
 * =================================================================== */
int main(void)
{
    int i, n;

    /* Build all 3 pattern databases */
    fprintf(stderr, "Building pattern databases...\n");
    for (i = 0; i < 3; i++) build_pdb(i);
    fprintf(stderr, "All PDBs built.\n");

    /* Read number of puzzles */
    if (scanf("%d", &n) != 1) {
        fprintf(stderr, "Failed to read puzzle count\n");
        return 1;
    }

    for (int p = 0; p < n; p++) {
        for (i = 0; i < NN; i++) {
            if (scanf("%d", &board[i]) != 1) {
                fprintf(stderr, "Failed to read tile %d of puzzle %d\n", i, p+1);
                return 1;
            }
            tpos[board[i]] = i;
        }
        blank = tpos[0];

        solve_puzzle();

        printf("%d", sol_len);
        for (i = 0; i < sol_len; i++)
            printf(" %c", dch[sol[i]]);
        printf("\n");

        fprintf(stderr, "Instance %d: %d moves\n", p + 1, sol_len);
    }

    for (i = 0; i < 3; i++) free(pdb[i]);
    return 0;
}
