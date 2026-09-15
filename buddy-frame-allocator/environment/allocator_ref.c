
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_ORDER 10
#define TOTAL_PAGES 16384
#define NR_ZONES 3
#define NR_MT 3

static const int ZS[] = {0, 1024, 12288};
static const int ZE[] = {1024, 12288, 16384};
static const int ZFB[][3] = {{-1,-1,-1},{0,-1,-1},{1,0,-1}};
static const int ZFBL[] = {0, 1, 2};
static const int MFB[][2] = {{2,1},{2,0},{1,0}};

typedef struct { int a, o, z, m, b; } PM;
static PM pg[TOTAL_PAGES];

typedef struct N { int p; struct N *n; } N;
static N *fl[NR_ZONES][NR_MT][MAX_ORDER+1];

static void fi(int z, int m, int o, int p) {
    N *nd = (N*)malloc(sizeof(N));
    nd->p = p;
    N **pp = &fl[z][m][o];
    while (*pp && (*pp)->p < p) pp = &(*pp)->n;
    nd->n = *pp;
    *pp = nd;
}

static int fr(int z, int m, int o, int p) {
    N **pp = &fl[z][m][o];
    while (*pp) {
        if ((*pp)->p == p) {
            N *d = *pp;
            *pp = d->n;
            free(d);
            return 1;
        }
        pp = &(*pp)->n;
    }
    return 0;
}

static int fp(int z, int m, int o) {
    N *h = fl[z][m][o];
    if (!h) return -1;
    int p = h->p;
    fl[z][m][o] = h->n;
    free(h);
    return p;
}

static int fc(int z, int m, int o) {
    int c = 0;
    for (N *n = fl[z][m][o]; n; n = n->n) c++;
    return c;
}

static void init(void) {
    int i;
    for (i = 0; i < TOTAL_PAGES; i++) {
        pg[i].a = 0; pg[i].o = -1; pg[i].z = -1;
        pg[i].m = -1; pg[i].b = -1;
    }
    memset(fl, 0, sizeof(fl));
    for (int z = 0; z < NR_ZONES; z++) {
        int p = ZS[z], e = ZE[z];
        while (p < e) {
            int o = MAX_ORDER;
            while (o > 0) {
                int s = 1 << o;
                if ((p % s == 0) && (p + s <= e)) break;
                o--;
            }
            fi(z, 1, o, p);
            p += (1 << o);
        }
    }
}

static int ta(int z, int m, int o) {
    int co;
    for (co = o; co <= MAX_ORDER; co++) {
        int p = fp(z, m, co);
        if (p >= 0) {
            int s;
            for (s = co - 1; s >= o; s--)
                fi(z, m, s, p + (1 << s));
            return p;
        }
    }
    return -1;
}

static int da(int o, int zp, int mt) {
    int zi, mi, nz, z, p, bs, i;
    int zl[NR_ZONES], ml[NR_MT];
    if (o < 0 || o > MAX_ORDER) return -1;
    nz = 0;
    zl[nz++] = zp;
    for (i = 0; i < ZFBL[zp]; i++) zl[nz++] = ZFB[zp][i];
    for (zi = 0; zi < nz; zi++) {
        z = zl[zi];
        ml[0] = mt; ml[1] = MFB[mt][0]; ml[2] = MFB[mt][1];
        for (mi = 0; mi < 3; mi++) {
            p = ta(z, ml[mi], o);
            if (p >= 0) {
                bs = 1 << o;
                for (i = 0; i < bs; i++) {
                    pg[p+i].a = 1; pg[p+i].o = o;
                    pg[p+i].z = z; pg[p+i].m = mt;
                    pg[p+i].b = p;
                }
                return p;
            }
        }
    }
    return -1;
}

static int df(int p, int o) {
    int z, mt, bs, i, cp, co, bd, f, m2;
    if (p < 0 || p >= TOTAL_PAGES) return -1;
    if (!pg[p].a || pg[p].b != p || pg[p].o != o) return -1;
    z = pg[p].z; mt = pg[p].m;
    bs = 1 << o;
    for (i = 0; i < bs; i++) {
        pg[p+i].a = 0; pg[p+i].o = -1; pg[p+i].z = -1;
        pg[p+i].m = -1; pg[p+i].b = -1;
    }
    cp = p; co = o;
    while (co < MAX_ORDER) {
        bd = cp ^ (1 << co);
        if (bd < ZS[z] || bd >= ZE[z]) break;
        f = 0;
        for (m2 = 0; m2 < NR_MT; m2++) {
            if (fr(z, m2, co, bd)) { f = 1; break; }
        }
        if (!f) break;
        if (bd < cp) cp = bd;
        co++;
    }
    fi(z, mt, co, cp);
    return 0;
}

static void ds(int z) {
    int fp2 = 0, o, m, c;
    printf("total_pages=%d nr_free=", ZE[z] - ZS[z]);
    for (o = 0; o <= MAX_ORDER; o++) {
        c = 0;
        for (m = 0; m < NR_MT; m++) c += fc(z, m, o);
        if (o > 0) printf(",");
        printf("%d", c);
        fp2 += c * (1 << o);
    }
    printf(" free_pages=%d\n", fp2);
}

static void di(int p) {
    if (p < 0 || p >= TOTAL_PAGES) { printf("NONE\n"); return; }
    printf("allocated=%d order=%d zone=%d migrate_type=%d base_pfn=%d\n",
           pg[p].a, pg[p].o, pg[p].z, pg[p].m, pg[p].b);
}

static int dc(int z) {
    int zs = ZS[z], ze = ZE[z];
    int ms = zs, fs2 = ze - 1, mv = 0;
    while (ms < fs2) {
        while (ms < fs2) {
            if (pg[ms].a && pg[ms].m == 1 && pg[ms].o == 0 && pg[ms].b == ms)
                break;
            ms++;
        }
        while (fs2 > ms) {
            if (!pg[fs2].a) break;
            fs2--;
        }
        if (ms >= fs2) break;
        int dst = fs2, found = 0, o, m;
        for (o = 0; o <= MAX_ORDER && !found; o++) {
            int bb = dst & ~((1 << o) - 1);
            if (bb < zs || bb + (1 << o) > ze) continue;
            for (m = 0; m < NR_MT && !found; m++) {
                if (fr(z, m, o, bb)) {
                    int cu = bb, co2 = o;
                    while (co2 > 0) {
                        co2--;
                        int h = 1 << co2;
                        if (dst >= cu + h) {
                            fi(z, m, co2, cu);
                            cu += h;
                        } else {
                            fi(z, m, co2, cu + h);
                        }
                    }
                    found = 1;
                }
            }
        }
        if (!found) { fs2--; continue; }
        int src = ms, smt = pg[src].m;
        pg[dst].a = 1; pg[dst].o = 0; pg[dst].z = z;
        pg[dst].m = smt; pg[dst].b = dst;
        pg[src].a = 0; pg[src].o = -1; pg[src].z = -1;
        pg[src].m = -1; pg[src].b = -1;
        int cp = src, co = 0;
        while (co < MAX_ORDER) {
            int bd = cp ^ (1 << co);
            if (bd < zs || bd >= ze) break;
            int fm = 0, m2;
            for (m2 = 0; m2 < NR_MT; m2++) {
                if (fr(z, m2, co, bd)) { fm = 1; break; }
            }
            if (!fm) break;
            if (bd < cp) cp = bd;
            co++;
        }
        fi(z, smt, co, cp);
        mv++; ms++; fs2--;
    }
    return mv;
}

static double dg(int z, int o) {
    int tf = 0, ord, m, c, sm;
    if (z < 0 || z >= NR_ZONES || o < 0 || o > MAX_ORDER) return -1.0;
    for (ord = 0; ord <= MAX_ORDER; ord++) {
        c = 0;
        for (m = 0; m < NR_MT; m++) c += fc(z, m, ord);
        tf += c * (1 << ord);
    }
    if (tf < (1 << o)) return -1.0;
    for (ord = o; ord <= MAX_ORDER; ord++) {
        for (m = 0; m < NR_MT; m++) {
            if (fc(z, m, ord) > 0) return 0.0;
        }
    }
    sm = 0;
    for (ord = 0; ord < o; ord++) {
        c = 0;
        for (m = 0; m < NR_MT; m++) c += fc(z, m, ord);
        sm += c * (1 << ord);
    }
    return (double)sm / (double)tf;
}

int main(void) {
    char cmd[64];
    int a, b, c;
    init();
    setbuf(stdout, NULL);
    while (scanf("%63s", cmd) == 1) {
        if (!strcmp(cmd, "ALLOC")) {
            scanf("%d %d %d", &a, &b, &c);
            printf("%d\n", da(a, b, c));
        } else if (!strcmp(cmd, "FREE")) {
            scanf("%d %d", &a, &b);
            printf("%s\n", df(a, b) == 0 ? "OK" : "ERROR");
        } else if (!strcmp(cmd, "STATS")) {
            scanf("%d", &a);
            ds(a);
        } else if (!strcmp(cmd, "INFO")) {
            scanf("%d", &a);
            di(a);
        } else if (!strcmp(cmd, "COMPACT")) {
            scanf("%d", &a);
            printf("%d\n", dc(a));
        } else if (!strcmp(cmd, "FRAG")) {
            scanf("%d %d", &a, &b);
            printf("%.6f\n", dg(a, b));
        } else if (!strcmp(cmd, "QUIT")) {
            break;
        }
    }
    return 0;
}
