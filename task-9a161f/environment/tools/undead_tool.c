/*
 * undead_tool.c - Undead puzzle verification and analysis tool.
 * Build: make
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXN 20
#define MAX_CELLS (MAXN * MAXN)

typedef struct {
    int n;
    char grid[MAXN][MAXN];
    int top[MAXN], bot[MAXN], lft[MAXN], rgt[MAXN];
    int ng, nv, nz;
} Puzzle;

typedef struct { int r, c, refl; } PathCell;

static int parse_id(const char *id, Puzzle *p) {
    int w, h;
    if (sscanf(id, "%dx%d:", &w, &h) != 2 || w != h || w < 2 || w > MAXN)
        return -1;
    p->n = w;
    const char *s = strchr(id, ':');
    if (!s) return -1;
    s++;
    int pos = 0, i = 0;
    while (s[i] && s[i] != ',') {
        char ch = s[i];
        if (ch >= 'a' && ch <= 'z') {
            int cnt = ch - 'a' + 1;
            while (cnt-- > 0 && pos < w * w) {
                p->grid[pos / w][pos % w] = '.';
                pos++;
            }
        } else if (ch == 'L') {
            if (pos < w * w) { p->grid[pos / w][pos % w] = '\\'; pos++; }
        } else if (ch == 'R') {
            if (pos < w * w) { p->grid[pos / w][pos % w] = '/'; pos++; }
        }
        i++;
    }
    if (pos != w * w) return -1;

    char *np = (char *)(s + i);
    int vals[MAX_CELLS], nv = 0;
    while (*np && nv < 4 * w + 3) {
        if (*np == ',') { np++; vals[nv++] = (int)strtol(np, &np, 10); }
        else np++;
    }
    if (nv != 4 * w + 3) return -1;

    for (int j = 0; j < w; j++) p->top[j] = vals[j];
    for (int j = 0; j < w; j++) p->bot[j] = vals[w + j];
    for (int j = 0; j < w; j++) p->lft[j] = vals[2 * w + j];
    for (int j = 0; j < w; j++) p->rgt[j] = vals[3 * w + j];
    p->ng = vals[4 * w];
    p->nv = vals[4 * w + 1];
    p->nz = vals[4 * w + 2];
    return 0;
}

static int trace(char g[MAXN][MAXN], int n,
                 int sr, int sc, int dir, PathCell *out, int mx) {
    static const int dr[] = {1, 0, -1, 0};
    static const int dc[] = {0, 1, 0, -1};
    int r = sr, c = sc, rf = 0, cnt = 0;
    char seen[MAXN][MAXN][4];
    memset(seen, 0, sizeof(seen));
    while (r >= 0 && r < n && c >= 0 && c < n) {
        if (seen[r][c][dir]) break;
        seen[r][c][dir] = 1;
        char cell = g[r][c];
        if (cell == '/') {
            static const int m[] = {3, 2, 1, 0};
            dir = m[dir]; rf = !rf;
        } else if (cell == '\\') {
            static const int m[] = {1, 0, 3, 2};
            dir = m[dir]; rf = !rf;
        } else {
            if (cnt < mx) { out[cnt].r = r; out[cnt].c = c; out[cnt].refl = rf; }
            cnt++;
        }
        r += dr[dir]; c += dc[dir];
    }
    return cnt;
}

static int vis(char m, int rf) {
    return m == 'Z' ? 1 : m == 'G' ? !rf : m == 'V' ? rf : 0;
}

static int cmd_info(const char *id) {
    Puzzle p;
    if (parse_id(id, &p)) { fprintf(stderr, "bad game id\n"); return 1; }
    int mir = 0, emp = 0;
    for (int r = 0; r < p.n; r++)
        for (int c = 0; c < p.n; c++)
            if (p.grid[r][c] == '/' || p.grid[r][c] == '\\') mir++; else emp++;
    printf("size=%d mirrors=%d empty=%d ghosts=%d vampires=%d zombies=%d\n",
           p.n, mir, emp, p.ng, p.nv, p.nz);
    printf("top:");
    for (int i = 0; i < p.n; i++) printf(" %d", p.top[i]);
    printf("\nbot:");
    for (int i = 0; i < p.n; i++) printf(" %d", p.bot[i]);
    printf("\nlft:");
    for (int i = 0; i < p.n; i++) printf(" %d", p.lft[i]);
    printf("\nrgt:");
    for (int i = 0; i < p.n; i++) printf(" %d", p.rgt[i]);
    printf("\n");
    return 0;
}

static int cmd_decode(const char *id) {
    Puzzle p;
    if (parse_id(id, &p)) { fprintf(stderr, "bad game id\n"); return 1; }
    for (int r = 0; r < p.n; r++) {
        for (int c = 0; c < p.n; c++) putchar(p.grid[r][c]);
        putchar('\n');
    }
    return 0;
}

static int cmd_verify(const char *id, const char *sf) {
    Puzzle p;
    if (parse_id(id, &p)) { fprintf(stderr, "bad game id\n"); return 1; }
    FILE *f = fopen(sf, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", sf); return 1; }
    char sol[MAXN][MAXN];
    int nr = 0;
    char line[256];
    while (fgets(line, sizeof(line), f) && nr < p.n) {
        int len = (int)strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) len--;
        if (len == 0) continue;
        if (len < p.n) {
            fprintf(stderr, "FAIL: row %d short (%d < %d)\n", nr, len, p.n);
            fclose(f); return 1;
        }
        for (int c = 0; c < p.n; c++) sol[nr][c] = line[c];
        nr++;
    }
    fclose(f);
    if (nr != p.n) {
        fprintf(stderr, "FAIL: got %d rows, need %d\n", nr, p.n);
        return 1;
    }

    for (int r = 0; r < p.n; r++)
        for (int c = 0; c < p.n; c++) {
            char pg = p.grid[r][c], sc = sol[r][c];
            if ((pg == '/' || pg == '\\') && sc != pg) {
                fprintf(stderr, "FAIL: mirror at (%d,%d) changed\n", r, c);
                return 1;
            }
            if (pg == '.' && sc != 'G' && sc != 'V' && sc != 'Z') {
                fprintf(stderr, "FAIL: invalid '%c' at (%d,%d)\n", sc, r, c);
                return 1;
            }
        }

    int gc = 0, vc = 0, zc = 0;
    for (int r = 0; r < p.n; r++)
        for (int c = 0; c < p.n; c++) {
            if (sol[r][c] == 'G') gc++;
            else if (sol[r][c] == 'V') vc++;
            else if (sol[r][c] == 'Z') zc++;
        }
    if (gc != p.ng || vc != p.nv || zc != p.nz) {
        fprintf(stderr, "FAIL: counts G=%d/%d V=%d/%d Z=%d/%d\n",
                gc, p.ng, vc, p.nv, zc, p.nz);
        return 1;
    }

    PathCell path[MAX_CELLS];
    int pc, v;

    for (int c = 0; c < p.n; c++) {
        pc = trace(sol, p.n, 0, c, 0, path, MAX_CELLS);
        v = 0; for (int j = 0; j < pc; j++) v += vis(sol[path[j].r][path[j].c], path[j].refl);
        if (v != p.top[c]) {
            fprintf(stderr, "FAIL: top[%d]=%d want %d\n", c, v, p.top[c]);
            return 1;
        }
    }
    for (int c = 0; c < p.n; c++) {
        pc = trace(sol, p.n, p.n - 1, c, 2, path, MAX_CELLS);
        v = 0; for (int j = 0; j < pc; j++) v += vis(sol[path[j].r][path[j].c], path[j].refl);
        if (v != p.bot[c]) {
            fprintf(stderr, "FAIL: bot[%d]=%d want %d\n", c, v, p.bot[c]);
            return 1;
        }
    }
    for (int r = 0; r < p.n; r++) {
        pc = trace(sol, p.n, r, 0, 1, path, MAX_CELLS);
        v = 0; for (int j = 0; j < pc; j++) v += vis(sol[path[j].r][path[j].c], path[j].refl);
        if (v != p.lft[r]) {
            fprintf(stderr, "FAIL: lft[%d]=%d want %d\n", r, v, p.lft[r]);
            return 1;
        }
    }
    for (int r = 0; r < p.n; r++) {
        pc = trace(sol, p.n, r, p.n - 1, 3, path, MAX_CELLS);
        v = 0; for (int j = 0; j < pc; j++) v += vis(sol[path[j].r][path[j].c], path[j].refl);
        if (v != p.rgt[r]) {
            fprintf(stderr, "FAIL: rgt[%d]=%d want %d\n", r, v, p.rgt[r]);
            return 1;
        }
    }

    printf("OK\n");
    return 0;
}

static void usage(void) {
    fprintf(stderr, "undead-tool: Undead puzzle toolkit\n");
    fprintf(stderr, "  undead-tool info    <game_id>\n");
    fprintf(stderr, "  undead-tool decode  <game_id>\n");
    fprintf(stderr, "  undead-tool verify  <game_id> <solution_file>\n");
}

int main(int argc, char **argv) {
    if (argc < 3) { usage(); return 1; }
    if (!strcmp(argv[1], "info")) return cmd_info(argv[2]);
    if (!strcmp(argv[1], "decode")) return cmd_decode(argv[2]);
    if (!strcmp(argv[1], "verify") && argc >= 4) return cmd_verify(argv[2], argv[3]);
    usage();
    return 1;
}
