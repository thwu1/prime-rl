/*
 * Polyomino Field Oracle Server
 * TCP line protocol on configurable port (default 9999).
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <signal.h>
#include <errno.h>
#include <ctype.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define MAX_N 50
#define MAX_M 10
#define MAX_SESSIONS 32
#define DEFAULT_PORT 9999
#define BUF_SIZE 131072
#define MAX_CELLS 2500

/* ================================================================
 * SplitMix64 RNG
 * ================================================================ */
typedef struct { uint64_t state; } sm64_t;

static uint64_t sm64_next(sm64_t *r) {
    uint64_t z = (r->state += UINT64_C(0x9e3779b97f4a7c15));
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    return z ^ (z >> 31);
}

static int sm64_int(sm64_t *r, int lo, int hi) {
    return lo + (int)(sm64_next(r) % (uint64_t)(hi - lo + 1));
}

static double sm64_double(sm64_t *r) {
    return ((double)(sm64_next(r) >> 11) + 0.5) / (double)(UINT64_C(1) << 53);
}

static double sm64_gauss(sm64_t *r, double mu, double sigma) {
    double u1 = sm64_double(r);
    double u2 = sm64_double(r);
    double z0 = sqrt(-2.0 * log(u1)) * cos(2.0 * M_PI * u2);
    return mu + sigma * z0;
}

/* ================================================================
 * Polyomino Shape Library
 * ================================================================ */
#define NUM_SHAPES 17
#define MAX_SHAPE_CELLS 6

static const int SHAPE_SIZES[NUM_SHAPES] = {
    3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 6, 6
};

static const int SHAPES[NUM_SHAPES][MAX_SHAPE_CELLS][2] = {
    /* 3-cell */
    {{0,0},{0,1},{1,0},{0,0},{0,0},{0,0}},
    {{0,0},{0,1},{0,2},{0,0},{0,0},{0,0}},
    {{0,0},{1,0},{1,1},{0,0},{0,0},{0,0}},
    /* 4-cell */
    {{0,0},{0,1},{0,2},{0,3},{0,0},{0,0}},
    {{0,0},{0,1},{1,0},{1,1},{0,0},{0,0}},
    {{0,0},{0,1},{0,2},{1,1},{0,0},{0,0}},
    {{0,0},{1,0},{1,1},{2,1},{0,0},{0,0}},
    {{0,1},{1,0},{1,1},{2,0},{0,0},{0,0}},
    {{0,0},{0,1},{0,2},{1,0},{0,0},{0,0}},
    {{0,0},{0,1},{0,2},{1,2},{0,0},{0,0}},
    /* 5-cell */
    {{0,0},{0,1},{0,2},{0,3},{0,4},{0,0}},
    {{0,0},{0,1},{0,2},{1,0},{2,0},{0,0}},
    {{0,0},{0,1},{1,1},{1,2},{2,2},{0,0}},
    {{0,0},{1,0},{1,1},{1,2},{2,2},{0,0}},
    {{0,1},{1,0},{1,1},{1,2},{2,1},{0,0}},
    /* 6-cell */
    {{0,0},{0,1},{0,2},{1,0},{1,1},{1,2}},
    {{0,0},{0,1},{0,2},{0,3},{1,0},{1,1}}
};

/* ================================================================
 * Case Parameters
 * ================================================================ */
#define NUM_CASES 5

typedef struct {
    uint64_t gen_seed;
    int N, M;
    double epsilon;
    uint64_t query_seed;
} CaseParams;

static const CaseParams CASES[NUM_CASES] = {
    {314159, 20, 4, 0.08, 271828},
    {141421, 20, 5, 0.08, 173205},
    {223606, 20, 5, 0.10, 244949},
    {264575, 20, 4, 0.12, 316227},
    {346410, 20, 6, 0.08, 374165}
};

/* ================================================================
 * Session State
 * ================================================================ */
typedef struct {
    int active;
    char sid[32];
    int case_id;
    int N, M;
    double epsilon;
    int grid[MAX_N][MAX_N];
    int poly_shapes[MAX_M][MAX_SHAPE_CELLS][2];
    int poly_sizes[MAX_M];
    int poly_dr[MAX_M];
    int poly_dc[MAX_M];
    sm64_t qrng;
    double cost;
    int num_ops;
    int max_ops;
} Session;

static Session sessions[MAX_SESSIONS];
static int next_sid = 1;

/* ================================================================
 * Shape Rotation (90 deg clockwise, normalize to origin)
 * ================================================================ */
static void rotate_shape_90(int src[][2], int size, int dst[][2]) {
    int i, mr, mc;
    for (i = 0; i < size; i++) {
        dst[i][0] = src[i][1];
        dst[i][1] = -src[i][0];
    }
    mr = dst[0][0]; mc = dst[0][1];
    for (i = 1; i < size; i++) {
        if (dst[i][0] < mr) mr = dst[i][0];
        if (dst[i][1] < mc) mc = dst[i][1];
    }
    for (i = 0; i < size; i++) {
        dst[i][0] -= mr;
        dst[i][1] -= mc;
    }
}

/* ================================================================
 * Session Initialization
 * ================================================================ */
static int init_session(int case_id, Session **out) {
    int slot, i, c, r;
    const CaseParams *cp;
    Session *s;
    sm64_t gen;
    int placed, attempts;

    if (case_id < 0 || case_id >= NUM_CASES) return -1;

    slot = -1;
    for (i = 0; i < MAX_SESSIONS; i++) {
        if (!sessions[i].active) { slot = i; break; }
    }
    if (slot < 0) return -2;

    cp = &CASES[case_id];
    s = &sessions[slot];
    memset(s, 0, sizeof(*s));
    s->active = 1;
    snprintf(s->sid, sizeof(s->sid), "s%04d", next_sid++);
    s->case_id = case_id;
    s->N = cp->N;
    s->M = cp->M;
    s->epsilon = cp->epsilon;
    s->max_ops = 2 * s->N * s->N;

    gen.state = cp->gen_seed;
    s->qrng.state = cp->query_seed;

    placed = 0; attempts = 0;
    while (placed < s->M && attempts < 10000) {
        int idx, rot_count, size, max_r, max_c, dr, dc;
        int shape[MAX_SHAPE_CELLS][2], tmp[MAX_SHAPE_CELLS][2];

        attempts++;
        idx = sm64_int(&gen, 0, NUM_SHAPES - 1);
        rot_count = sm64_int(&gen, 0, 3);
        size = SHAPE_SIZES[idx];

        for (c = 0; c < size; c++) {
            shape[c][0] = SHAPES[idx][c][0];
            shape[c][1] = SHAPES[idx][c][1];
        }
        for (r = 0; r < rot_count; r++) {
            rotate_shape_90(shape, size, tmp);
            memcpy(shape, tmp, sizeof(int) * MAX_SHAPE_CELLS * 2);
        }

        max_r = 0; max_c = 0;
        for (c = 0; c < size; c++) {
            if (shape[c][0] > max_r) max_r = shape[c][0];
            if (shape[c][1] > max_c) max_c = shape[c][1];
        }
        if (max_r >= s->N || max_c >= s->N) continue;

        dr = sm64_int(&gen, 0, s->N - 1 - max_r);
        dc = sm64_int(&gen, 0, s->N - 1 - max_c);

        for (c = 0; c < size; c++)
            s->grid[shape[c][0] + dr][shape[c][1] + dc]++;

        for (c = 0; c < size; c++) {
            s->poly_shapes[placed][c][0] = shape[c][0];
            s->poly_shapes[placed][c][1] = shape[c][1];
        }
        s->poly_sizes[placed] = size;
        s->poly_dr[placed] = dr;
        s->poly_dc[placed] = dc;
        placed++;
    }

    *out = s;
    return 0;
}

/* ================================================================
 * Find Session by ID
 * ================================================================ */
static Session *find_session(const char *sid) {
    int i;
    for (i = 0; i < MAX_SESSIONS; i++) {
        if (sessions[i].active && strcmp(sessions[i].sid, sid) == 0)
            return &sessions[i];
    }
    return NULL;
}

/* ================================================================
 * Query Operations
 * ================================================================ */
static int op_drill(Session *s, int i, int j, double *cost, double *total) {
    if (i < 0 || i >= s->N || j < 0 || j >= s->N) return -1;
    if (s->num_ops >= s->max_ops) return -2;
    s->cost += 1.0;
    s->num_ops++;
    *cost = 1.0;
    *total = s->cost;
    return s->grid[i][j];
}

static int op_divine(Session *s, int cells[][2], int k,
                     double *cost_out, double *total_out) {
    int c, v;
    double eps, mu, sigma, x, qcost;
    int result;

    if (k < 2) return -1;
    if (s->num_ops >= s->max_ops) return -2;
    for (c = 0; c < k; c++) {
        if (cells[c][0] < 0 || cells[c][0] >= s->N ||
            cells[c][1] < 0 || cells[c][1] >= s->N) return -1;
    }

    v = 0;
    for (c = 0; c < k; c++)
        v += s->grid[cells[c][0]][cells[c][1]];

    eps = s->epsilon;
    mu = (k - v) * eps + v * (1.0 - eps);
    sigma = sqrt((double)k * eps * (1.0 - eps));
    x = sm64_gauss(&s->qrng, mu, sigma);
    result = (int)round(x);
    if (result < 0) result = 0;

    qcost = 1.0 / sqrt((double)k);
    s->cost += qcost;
    s->num_ops++;
    *cost_out = qcost;
    *total_out = s->cost;
    return result;
}

static int op_submit(Session *s, int cells[][2], int ncells,
                     int *correct, double *prec, double *recall, double *total) {
    int truth[MAX_N * MAX_N][2];
    int tcount = 0;
    int tp = 0;
    int i, j, a, t;

    for (i = 0; i < s->N; i++)
        for (j = 0; j < s->N; j++)
            if (s->grid[i][j] > 0) {
                truth[tcount][0] = i;
                truth[tcount][1] = j;
                tcount++;
            }

    for (a = 0; a < ncells; a++) {
        for (t = 0; t < tcount; t++) {
            if (cells[a][0] == truth[t][0] && cells[a][1] == truth[t][1]) {
                tp++;
                break;
            }
        }
    }

    *prec = ncells > 0 ? (double)tp / ncells : 0.0;
    *recall = tcount > 0 ? (double)tp / tcount : 0.0;
    *correct = (tp == tcount && tp == ncells) ? 1 : 0;
    *total = s->cost;
    return 0;
}

/* ================================================================
 * Parse cell list: "i1,j1;i2,j2;..."
 * ================================================================ */
static int parse_cells(const char *str, int cells[][2], int max_cells) {
    int count = 0;
    const char *p = str;
    while (*p && count < max_cells) {
        int i, j;
        if (sscanf(p, "%d,%d", &i, &j) != 2) break;
        cells[count][0] = i;
        cells[count][1] = j;
        count++;
        while (*p && *p != ';') p++;
        if (*p == ';') p++;
    }
    return count;
}

/* ================================================================
 * Command Handler
 * Returns 1 if client should disconnect
 * ================================================================ */
static int handle_command(const char *line, char *resp, int rsz) {
    char cmd[32] = {0};
    int ci = 0;

    while (*line && isspace((unsigned char)*line)) line++;
    if (!*line) { snprintf(resp, rsz, "ERROR empty_command"); return 0; }

    while (*line && !isspace((unsigned char)*line) && ci < 30)
        cmd[ci++] = (char)toupper((unsigned char)*line++);
    cmd[ci] = 0;
    while (*line && isspace((unsigned char)*line)) line++;

    if (strcmp(cmd, "PING") == 0) {
        snprintf(resp, rsz, "PONG");
        return 0;
    }
    if (strcmp(cmd, "QUIT") == 0) {
        snprintf(resp, rsz, "BYE");
        return 1;
    }
    if (strcmp(cmd, "INIT") == 0) {
        int case_id;
        Session *s;
        int rc;
        char sbuf[8192];
        int pos = 0;
        int m, c;

        if (sscanf(line, "%d", &case_id) != 1) {
            snprintf(resp, rsz, "ERROR invalid_case_id");
            return 0;
        }
        rc = init_session(case_id, &s);
        if (rc == -1) {
            snprintf(resp, rsz, "ERROR case_id_must_be_0_to_%d", NUM_CASES - 1);
            return 0;
        }
        if (rc == -2) {
            snprintf(resp, rsz, "ERROR max_sessions_reached");
            return 0;
        }

        for (m = 0; m < s->M; m++) {
            if (m > 0) sbuf[pos++] = '|';
            for (c = 0; c < s->poly_sizes[m]; c++) {
                if (c > 0) sbuf[pos++] = ';';
                pos += snprintf(sbuf + pos, sizeof(sbuf) - pos,
                    "%d,%d", s->poly_shapes[m][c][0], s->poly_shapes[m][c][1]);
            }
        }
        sbuf[pos] = 0;

        snprintf(resp, rsz,
            "SESSION %s N=%d M=%d EPS=%.6f MAXOPS=%d SHAPES=%s",
            s->sid, s->N, s->M, s->epsilon, s->max_ops, sbuf);
        return 0;
    }
    if (strcmp(cmd, "DRILL") == 0) {
        char sid[32];
        int i, j, val;
        double cost, total;
        Session *s;

        if (sscanf(line, "%31s %d %d", sid, &i, &j) != 3) {
            snprintf(resp, rsz, "ERROR usage_DRILL_sid_i_j");
            return 0;
        }
        s = find_session(sid);
        if (!s) { snprintf(resp, rsz, "ERROR unknown_session"); return 0; }

        val = op_drill(s, i, j, &cost, &total);
        if (val == -1) { snprintf(resp, rsz, "ERROR out_of_bounds"); return 0; }
        if (val == -2) { snprintf(resp, rsz, "ERROR max_ops_exceeded"); return 0; }

        snprintf(resp, rsz, "OK VALUE=%d COST=%.6f TOTAL=%.6f OPS=%d",
            val, cost, total, s->num_ops);
        return 0;
    }
    if (strcmp(cmd, "DIVINE") == 0) {
        char sid[32];
        int cells[MAX_CELLS][2];
        int k, val;
        double cost, total;
        Session *s;

        if (sscanf(line, "%31s", sid) != 1) {
            snprintf(resp, rsz, "ERROR usage_DIVINE_sid_cells");
            return 0;
        }
        while (*line && !isspace((unsigned char)*line)) line++;
        while (*line && isspace((unsigned char)*line)) line++;

        s = find_session(sid);
        if (!s) { snprintf(resp, rsz, "ERROR unknown_session"); return 0; }

        k = parse_cells(line, cells, MAX_CELLS);
        if (k < 2) {
            snprintf(resp, rsz, "ERROR divine_requires_at_least_2_cells");
            return 0;
        }

        val = op_divine(s, cells, k, &cost, &total);
        if (val == -1) { snprintf(resp, rsz, "ERROR invalid_cells"); return 0; }
        if (val == -2) { snprintf(resp, rsz, "ERROR max_ops_exceeded"); return 0; }

        snprintf(resp, rsz, "OK VALUE=%d COST=%.6f TOTAL=%.6f OPS=%d",
            val, cost, total, s->num_ops);
        return 0;
    }
    if (strcmp(cmd, "SUBMIT") == 0) {
        char sid[32];
        int cells[MAX_CELLS][2];
        int ncells, correct;
        double prec, recall, total;
        Session *s;

        if (sscanf(line, "%31s", sid) != 1) {
            snprintf(resp, rsz, "ERROR usage_SUBMIT_sid_cells");
            return 0;
        }
        while (*line && !isspace((unsigned char)*line)) line++;
        while (*line && isspace((unsigned char)*line)) line++;

        s = find_session(sid);
        if (!s) { snprintf(resp, rsz, "ERROR unknown_session"); return 0; }

        ncells = parse_cells(line, cells, MAX_CELLS);
        op_submit(s, cells, ncells, &correct, &prec, &recall, &total);

        snprintf(resp, rsz, "OK CORRECT=%d PREC=%.6f RECALL=%.6f TOTAL=%.6f",
            correct, prec, recall, total);
        return 0;
    }
    if (strcmp(cmd, "STATUS") == 0) {
        char sid[32];
        Session *s;

        if (sscanf(line, "%31s", sid) != 1) {
            snprintf(resp, rsz, "ERROR usage_STATUS_sid");
            return 0;
        }
        s = find_session(sid);
        if (!s) { snprintf(resp, rsz, "ERROR unknown_session"); return 0; }

        snprintf(resp, rsz, "OK COST=%.6f OPS=%d MAXOPS=%d",
            s->cost, s->num_ops, s->max_ops);
        return 0;
    }

    snprintf(resp, rsz, "ERROR unknown_command_%s", cmd);
    return 0;
}

/* ================================================================
 * TCP Server
 * ================================================================ */
static volatile int running = 1;

static void sighandler(int sig) { (void)sig; running = 0; }

int main(int argc, char *argv[]) {
    int port = DEFAULT_PORT;
    int server_fd, client_fd, opt;
    struct sockaddr_in addr;

    if (argc > 1) port = atoi(argv[1]);

    signal(SIGTERM, sighandler);
    signal(SIGINT, sighandler);
    signal(SIGPIPE, SIG_IGN);

    server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) { perror("socket"); return 1; }

    opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons(port);

    if (bind(server_fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); close(server_fd); return 1;
    }
    if (listen(server_fd, 5) < 0) {
        perror("listen"); close(server_fd); return 1;
    }

    fprintf(stderr, "poly_server listening on 127.0.0.1:%d\n", port);
    fflush(stderr);

    while (running) {
        FILE *fin, *fout;
        char line[BUF_SIZE];
        int dup_fd;

        client_fd = accept(server_fd, NULL, NULL);
        if (client_fd < 0) {
            if (errno == EINTR) continue;
            perror("accept");
            break;
        }

        dup_fd = dup(client_fd);
        if (dup_fd < 0) { close(client_fd); continue; }

        fin = fdopen(dup_fd, "r");
        fout = fdopen(client_fd, "w");
        if (!fin || !fout) {
            if (fin) fclose(fin); else close(dup_fd);
            if (fout) fclose(fout); else close(client_fd);
            continue;
        }

        while (running && fgets(line, sizeof(line), fin)) {
            char response[BUF_SIZE];
            int len = strlen(line);
            int quit;

            while (len > 0 && (line[len-1] == '\n' || line[len-1] == '\r'))
                line[--len] = 0;

            quit = handle_command(line, response, sizeof(response));
            fprintf(fout, "%s\n", response);
            fflush(fout);
            if (quit) break;
        }

        fclose(fin);
        fclose(fout);
    }

    close(server_fd);
    return 0;
}
