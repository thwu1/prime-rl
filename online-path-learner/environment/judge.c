/* Online Shortest Path Judge — compiled and stripped at build time */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
#include <signal.h>
#include <stdint.h>

#define NR 30
#define NC 30
#define NV (NR * NC)
#define NQ 1000
#define INF 0x7FFFFFFF

/* SplitMix64 PRNG */
typedef struct { uint64_t s; } Rng;

static uint64_t rng_next(Rng *r) {
    uint64_t z = (r->s += UINT64_C(0x9e3779b97f4a7c15));
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    return z ^ (z >> 31);
}

static int rng_int(Rng *r, int lo, int hi) {
    return lo + (int)(rng_next(r) % (uint64_t)(hi - lo + 1));
}

static double rng_dbl(Rng *r) {
    return (rng_next(r) >> 11) * (1.0 / (double)(UINT64_C(1) << 53));
}

/* Graph edge weights */
static int hw[NR][NC - 1];  /* horizontal */
static int vw[NR - 1][NC];  /* vertical */

/* Min-heap for Dijkstra */
typedef struct { int d, n; } HNode;
static HNode heap[NV * 4];
static int hsz;

static void hpush(int d, int n) {
    int i = hsz++;
    heap[i].d = d; heap[i].n = n;
    while (i > 0) {
        int p = (i - 1) / 2;
        if (heap[p].d <= heap[i].d) break;
        HNode t = heap[p]; heap[p] = heap[i]; heap[i] = t;
        i = p;
    }
}

static HNode hpop(void) {
    HNode top = heap[0];
    heap[0] = heap[--hsz];
    int i = 0;
    for (;;) {
        int l = 2 * i + 1, r = 2 * i + 2, s = i;
        if (l < hsz && heap[l].d < heap[s].d) s = l;
        if (r < hsz && heap[r].d < heap[s].d) s = r;
        if (s == i) break;
        HNode t = heap[i]; heap[i] = heap[s]; heap[s] = t;
        i = s;
    }
    return top;
}

static int dist[NV];

static int dijkstra(int si, int sj, int ti, int tj) {
    int src = si * NC + sj, dst = ti * NC + tj;
    for (int i = 0; i < NV; i++) dist[i] = INF;
    dist[src] = 0; hsz = 0; hpush(0, src);
    while (hsz > 0) {
        HNode e = hpop();
        if (e.d > dist[e.n]) continue;
        if (e.n == dst) break;
        int ui = e.n / NC, uj = e.n % NC;
        if (uj < NC - 1) {
            int w = hw[ui][uj], nd = e.d + w;
            if (nd < dist[e.n + 1]) { dist[e.n + 1] = nd; hpush(nd, e.n + 1); }
        }
        if (uj > 0) {
            int w = hw[ui][uj - 1], nd = e.d + w;
            if (nd < dist[e.n - 1]) { dist[e.n - 1] = nd; hpush(nd, e.n - 1); }
        }
        if (ui < NR - 1) {
            int w = vw[ui][uj], nd = e.d + w;
            if (nd < dist[e.n + NC]) { dist[e.n + NC] = nd; hpush(nd, e.n + NC); }
        }
        if (ui > 0) {
            int w = vw[ui - 1][uj], nd = e.d + w;
            if (nd < dist[e.n - NC]) { dist[e.n - NC] = nd; hpush(nd, e.n - NC); }
        }
    }
    return dist[dst];
}

/* Query data */
static struct { int si, sj, ti, tj, opt; double noise; } queries[NQ];

static void generate(uint64_t seed) {
    Rng rng = { seed };
    int D = rng_int(&rng, 100, 2000);
    int M = rng_int(&rng, 1, 2);

    for (int i = 0; i < NR; i++) {
        int base[2];
        for (int p = 0; p < M; p++) base[p] = rng_int(&rng, 1000 + D, 9000 - D);
        if (M == 1) {
            for (int j = 0; j < NC - 1; j++)
                hw[i][j] = base[0] + rng_int(&rng, -D, D);
        } else {
            int x = rng_int(&rng, 1, 28);
            for (int j = 0; j < NC - 1; j++)
                hw[i][j] = base[j < x ? 0 : 1] + rng_int(&rng, -D, D);
        }
    }

    for (int j = 0; j < NC; j++) {
        int base[2];
        for (int p = 0; p < M; p++) base[p] = rng_int(&rng, 1000 + D, 9000 - D);
        if (M == 1) {
            for (int i = 0; i < NR - 1; i++)
                vw[i][j] = base[0] + rng_int(&rng, -D, D);
        } else {
            int y = rng_int(&rng, 1, 28);
            for (int i = 0; i < NR - 1; i++)
                vw[i][j] = base[i < y ? 0 : 1] + rng_int(&rng, -D, D);
        }
    }

    for (int q = 0; q < NQ; q++) {
        int si, sj, ti, tj;
        do {
            si = rng_int(&rng, 0, 29); sj = rng_int(&rng, 0, 29);
            ti = rng_int(&rng, 0, 29); tj = rng_int(&rng, 0, 29);
        } while (abs(si - ti) + abs(sj - tj) < 10);
        queries[q].si = si; queries[q].sj = sj;
        queries[q].ti = ti; queries[q].tj = tj;
        queries[q].opt = dijkstra(si, sj, ti, tj);
        queries[q].noise = 0.9 + 0.2 * rng_dbl(&rng);
    }
}

static int path_cost(const char *path, int si, int sj, int ti, int tj) {
    int ci = si, cj = sj, total = 0;
    for (int k = 0; path[k] && path[k] != '\n' && path[k] != '\r'; k++) {
        switch (path[k]) {
            case 'U': if (ci <= 0) return -1; ci--; total += vw[ci][cj]; break;
            case 'D': if (ci >= NR - 1) return -1; total += vw[ci][cj]; ci++; break;
            case 'L': if (cj <= 0) return -1; cj--; total += hw[ci][cj]; break;
            case 'R': if (cj >= NC - 1) return -1; total += hw[ci][cj]; cj++; break;
            default: return -1;
        }
    }
    return (ci == ti && cj == tj) ? total : -1;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <seed> <cmd...>\n", argv[0]);
        return 1;
    }
    signal(SIGPIPE, SIG_IGN);
    generate(strtoull(argv[1], NULL, 10));

    int p2c[2], c2p[2];
    if (pipe(p2c) < 0 || pipe(c2p) < 0) { perror("pipe"); return 1; }
    pid_t pid = fork();
    if (pid < 0) { perror("fork"); return 1; }

    if (pid == 0) {
        close(p2c[1]); close(c2p[0]);
        dup2(p2c[0], STDIN_FILENO);
        dup2(c2p[1], STDOUT_FILENO);
        close(p2c[0]); close(c2p[1]);
        execvp(argv[2], argv + 2);
        perror("exec"); _exit(1);
    }

    close(p2c[0]); close(c2p[1]);
    FILE *wr = fdopen(p2c[1], "w");
    FILE *rd = fdopen(c2p[0], "r");
    if (!wr || !rd) { fprintf(stderr, "fdopen failed\n"); return 1; }

    char buf[4096];
    double score = 0.0;

    for (int k = 0; k < NQ; k++) {
        fprintf(wr, "%d %d %d %d\n",
                queries[k].si, queries[k].sj,
                queries[k].ti, queries[k].tj);
        fflush(wr);

        if (!fgets(buf, sizeof(buf), rd)) {
            fprintf(stderr, "No output at query %d\n", k);
            printf("0\n");
            kill(pid, SIGKILL); waitpid(pid, NULL, 0);
            return 0;
        }
        int len = strlen(buf);
        while (len > 0 && (buf[len - 1] == '\n' || buf[len - 1] == '\r'))
            buf[--len] = '\0';

        int b = path_cost(buf, queries[k].si, queries[k].sj,
                          queries[k].ti, queries[k].tj);
        if (b < 0) {
            fprintf(stderr, "Invalid path at query %d\n", k);
            printf("0\n");
            kill(pid, SIGKILL); waitpid(pid, NULL, 0);
            return 0;
        }

        int fb = (int)(b * queries[k].noise + 0.5);
        fprintf(wr, "%d\n", fb);
        fflush(wr);

        score = score * 0.998 + (double)queries[k].opt / (double)b;
    }

    fclose(wr);
    waitpid(pid, NULL, 0);
    fclose(rd);

    printf("%lld\n", (long long)(2312311.0 * score + 0.5));
    return 0;
}
