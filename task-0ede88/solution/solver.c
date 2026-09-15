/*
 * solver.c - 15-puzzle optimal solver
 * Uses IDA* with blank-tracking disjoint pattern databases.
 * Partition: {1,2,3,4}, {5,6,7,8}, {9,10,11,12}, {13,14,15}
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define W 4
#define NN 16
#define MAXD 85
#define INF 255

/* PDB index sizes (wasteful but fast direct indexing) */
#define SZ5 1048576  /* 16^5 for 4-tile + blank groups */
#define SZ4 65536    /* 16^4 for 3-tile + blank group  */

/* ---- Deque for 0-1 BFS ---- */
#define DQN (1 << 22)
#define DQM (DQN - 1)
static int dq[DQN];
static int dqf, dqb;
static void dq_init(void)       { dqf = dqb = 0; }
static void dq_pushf(int v)     { dqf = (dqf - 1) & DQM; dq[dqf] = v; }
static void dq_pushb(int v)     { dq[dqb] = v; dqb = (dqb + 1) & DQM; }
static int  dq_popf(void)       { int v = dq[dqf]; dqf = (dqf + 1) & DQM; return v; }
static int  dq_empty(void)      { return dqf == dqb; }

/* ---- Adjacency ---- */
static int nadj[NN];
static int adj[NN][4];

static void init_adj(void) {
    for (int p = 0; p < NN; p++) {
        int r = p / W, c = p % W, n = 0;
        if (r > 0)     adj[p][n++] = p - W;
        if (r < W - 1) adj[p][n++] = p + W;
        if (c > 0)     adj[p][n++] = p - 1;
        if (c < W - 1) adj[p][n++] = p + 1;
        nadj[p] = n;
    }
}

/* ---- Group definitions ---- */
static const int grp[4][4] = {
    {1, 2, 3, 4}, {5, 6, 7, 8}, {9, 10, 11, 12}, {13, 14, 15, -1}
};
static const int gsz[4] = {4, 4, 4, 3};

/* ---- PDB storage ---- */
static unsigned char pdb0[SZ5], pdb1[SZ5], pdb2[SZ5], pdb3[SZ4];
static unsigned char *pdbs[4];
static unsigned char vis[SZ5];  /* reused per group build */

/* ---- Encoding / Decoding ---- */
static inline int enc5(int a, int b, int c, int d, int e) {
    return ((((a << 4 | b) << 4 | c) << 4 | d) << 4 | e);
}
static inline int enc4(int a, int b, int c, int d) {
    return (((a << 4 | b) << 4 | c) << 4 | d);
}
static inline void dec5(int x, int *a, int *b, int *c, int *d, int *e) {
    *e = x & 15; x >>= 4; *d = x & 15; x >>= 4;
    *c = x & 15; x >>= 4; *b = x & 15; x >>= 4; *a = x;
}
static inline void dec4(int x, int *a, int *b, int *c, int *d) {
    *d = x & 15; x >>= 4; *c = x & 15; x >>= 4;
    *b = x & 15; x >>= 4; *a = x;
}

/* ---- Build one PDB via 0-1 BFS from goal abstract state ---- */
static void build_pdb(int g) {
    int K = gsz[g];
    int sz = (K == 4) ? SZ5 : SZ4;
    unsigned char *db = pdbs[g];

    memset(db, INF, sz);
    memset(vis, 0, sz);

    /* Goal abstract state: blank at 0, tile t at position t */
    int gi;
    if (K == 4)
        gi = enc5(0, grp[g][0], grp[g][1], grp[g][2], grp[g][3]);
    else
        gi = enc4(0, grp[g][0], grp[g][1], grp[g][2]);

    db[gi] = 0;
    dq_init();
    dq_pushb(gi);

    while (!dq_empty()) {
        int idx = dq_popf();
        if (vis[idx]) continue;
        vis[idx] = 1;

        int cost = db[idx];
        int bl, tp[4];
        if (K == 4) dec5(idx, &bl, &tp[0], &tp[1], &tp[2], &tp[3]);
        else        dec4(idx, &bl, &tp[0], &tp[1], &tp[2]);

        for (int d = 0; d < nadj[bl]; d++) {
            int nb = adj[bl][d];

            /* Is nb occupied by a group tile? */
            int ti = -1;
            for (int j = 0; j < K; j++)
                if (tp[j] == nb) { ti = j; break; }

            int ni, nc;
            if (ti >= 0) {
                /* Swap blank and group tile: cost + 1 */
                int sv = tp[ti];
                tp[ti] = bl;
                ni = (K == 4) ? enc5(nb, tp[0], tp[1], tp[2], tp[3])
                              : enc4(nb, tp[0], tp[1], tp[2]);
                tp[ti] = sv;
                nc = cost + 1;
            } else {
                /* Move blank to non-group cell: cost + 0 */
                ni = (K == 4) ? enc5(nb, tp[0], tp[1], tp[2], tp[3])
                              : enc4(nb, tp[0], tp[1], tp[2]);
                nc = cost;
            }

            if (nc < db[ni]) {
                db[ni] = (unsigned char)nc;
                if (nc == cost) dq_pushf(ni);
                else            dq_pushb(ni);
            }
        }
    }
}

/* ---- Heuristic: sum of PDB lookups ---- */
static inline int heur(const int *pos) {
    int b = pos[0];
    return pdb0[enc5(b, pos[1],  pos[2],  pos[3],  pos[4])]
         + pdb1[enc5(b, pos[5],  pos[6],  pos[7],  pos[8])]
         + pdb2[enc5(b, pos[9],  pos[10], pos[11], pos[12])]
         + pdb3[enc4(b, pos[13], pos[14], pos[15])];
}

/* ---- IDA* search ---- */
static int path[MAXD];
static int sol_len;

static int dfs(int *board, int *pos, int g, int lim, int prev_bl, int depth) {
    int h = heur(pos);
    int f = g + h;
    if (f > lim) return f;
    if (h == 0) { sol_len = depth; return -1; }

    int mn = 9999;
    int bl = pos[0];

    for (int d = 0; d < nadj[bl]; d++) {
        int nb = adj[bl][d];
        if (nb == prev_bl) continue;   /* don't undo last move */

        int tile = board[nb];

        /* make move */
        board[bl] = tile; board[nb] = 0;
        pos[tile] = bl;   pos[0] = nb;

        /* record direction for output */
        int dir;
        if      (nb == bl - W) dir = 0;  /* U */
        else if (nb == bl + W) dir = 1;  /* D */
        else if (nb == bl - 1) dir = 2;  /* L */
        else                   dir = 3;  /* R */
        path[depth] = dir;

        int t = dfs(board, pos, g + 1, lim, bl, depth + 1);
        if (t < 0) {
            /* undo and propagate solution found */
            board[nb] = tile; board[bl] = 0;
            pos[0] = bl; pos[tile] = nb;
            return -1;
        }
        if (t < mn) mn = t;

        /* undo move */
        board[nb] = tile; board[bl] = 0;
        pos[0] = bl; pos[tile] = nb;
    }
    return mn;
}

static int solve(int *board, int *pos) {
    sol_len = -1;
    int lim = heur(pos);
    if (lim == 0) { sol_len = 0; return 0; }
    for (;;) {
        int t = dfs(board, pos, 0, lim, -1, 0);
        if (t < 0) return sol_len;
        if (t >= 9999) return -1;  /* should not happen for solvable puzzles */
        lim = t;
    }
}

/* ---- Main ---- */
int main(void) {
    static const char *dn = "UDLR";

    pdbs[0] = pdb0; pdbs[1] = pdb1; pdbs[2] = pdb2; pdbs[3] = pdb3;
    init_adj();

    for (int g = 0; g < 4; g++) {
        fprintf(stderr, "Building PDB %d (tiles", g);
        for (int j = 0; j < gsz[g]; j++) fprintf(stderr, " %d", grp[g][j]);
        fprintf(stderr, ")...\n");
        build_pdb(g);
    }
    fprintf(stderr, "All PDBs built.\n");

    FILE *fin = fopen("/app/puzzles.txt", "r");
    if (!fin) { perror("/app/puzzles.txt"); return 1; }

    FILE *fout = fopen("/app/results.json", "w");
    if (!fout) { perror("/app/results.json"); return 1; }

    fprintf(fout, "{\n");
    char line[512];
    int first = 1;

    while (fgets(line, sizeof(line), fin)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') continue;

        int id, tiles[16];
        if (sscanf(line, "%d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d",
                   &id, &tiles[0], &tiles[1], &tiles[2], &tiles[3],
                   &tiles[4], &tiles[5], &tiles[6], &tiles[7],
                   &tiles[8], &tiles[9], &tiles[10], &tiles[11],
                   &tiles[12], &tiles[13], &tiles[14], &tiles[15]) != 17)
            continue;

        int board[16], pos[16];
        for (int i = 0; i < 16; i++) {
            board[i] = tiles[i];
            pos[tiles[i]] = i;
        }

        fprintf(stderr, "Solving instance %d ...\n", id);
        int len = solve(board, pos);
        fprintf(stderr, "  => optimal length = %d\n", len);

        if (!first) fprintf(fout, ",\n");
        first = 0;

        fprintf(fout, "  \"%d\": {\"length\": %d, \"moves\": \"", id, len);
        for (int i = 0; i < len; i++) fputc(dn[path[i]], fout);
        fprintf(fout, "\"}");
    }

    fprintf(fout, "\n}\n");
    fclose(fin);
    fclose(fout);
    fprintf(stderr, "Done.\n");
    return 0;
}
