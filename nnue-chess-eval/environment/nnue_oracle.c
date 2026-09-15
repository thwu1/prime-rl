/*
 * NNUE chess position evaluator — compiled oracle binary.
 * Usage:
 *   nnue_oracle eval <FEN fields...>
 *   nnue_oracle features <FEN fields...>
 *   nnue_oracle probe <FEN fields...>
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define INPUT_SIZE  768
#define HIDDEN_SIZE 32
#define NUM_BUCKETS 4
#define QA    255
#define QB    64
#define SCALE 400
#define EMPTY_SQ -1

static const int BUCKET_MAP[64] = {
    0,0,1,1,1,1,0,0,
    0,0,1,1,1,1,0,0,
    2,2,2,2,2,2,2,2,
    2,2,2,2,2,2,2,2,
    2,2,2,2,2,2,2,2,
    3,3,3,3,3,3,3,3,
    3,3,3,3,3,3,3,3,
    3,3,3,3,3,3,3,3,
};

static const int PHASE_WT[6] = {0, 3, 3, 5, 10, 0};

static int16_t g_iw[NUM_BUCKETS][INPUT_SIZE][HIDDEN_SIZE];
static int16_t g_ib[HIDDEN_SIZE];
static int16_t g_ow[2 * HIDDEN_SIZE];
static int16_t g_ob;

static int g_board[64];
static int g_wtm;
static int g_hmc;

static void load_network(void) {
    FILE *f = fopen("/app/network.bin", "rb");
    if (!f) { exit(1); }
    fread(g_iw, 2, NUM_BUCKETS * INPUT_SIZE * HIDDEN_SIZE, f);
    fread(g_ib, 2, HIDDEN_SIZE, f);
    fread(g_ow, 2, 2 * HIDDEN_SIZE, f);
    fread(&g_ob, 2, 1, f);
    fclose(f);
}

static int encode_piece(char c) {
    int base = (c >= 'A' && c <= 'Z') ? 0 : 6;
    char lc = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c;
    switch (lc) {
        case 'p': return base;
        case 'n': return base + 1;
        case 'b': return base + 2;
        case 'r': return base + 3;
        case 'q': return base + 4;
        case 'k': return base + 5;
        default:  return EMPTY_SQ;
    }
}

static void parse_fen(const char *fen) {
    int r = 7, fl = 0;
    for (int i = 0; i < 64; i++) g_board[i] = EMPTY_SQ;
    const char *p = fen;
    while (*p && *p != ' ') {
        if (*p == '/') { r--; fl = 0; }
        else if (*p >= '1' && *p <= '8') fl += *p - '0';
        else { g_board[r * 8 + fl] = encode_piece(*p); fl++; }
        p++;
    }
    while (*p == ' ') p++;
    g_wtm = (*p == 'w') ? 1 : 0;
    p++;
    while (*p == ' ') p++;
    while (*p && *p != ' ') p++;
    while (*p == ' ') p++;
    while (*p && *p != ' ') p++;
    while (*p == ' ') p++;
    g_hmc = (*p) ? atoi(p) : 0;
}

static int find_king(int white) {
    int target = white ? 5 : 11;
    for (int i = 0; i < 64; i++)
        if (g_board[i] == target) return i;
    return -1;
}

static int should_mirror(int ksq) {
    return (ksq & 7) > 3;
}

static int get_bucket(int ksq, int white) {
    int sq = white ? ksq : (ksq ^ 56);
    return BUCKET_MAP[sq];
}

static int compute_features(int wp, int *buf) {
    int k = find_king(wp);
    int m = should_mirror(k);
    int cnt = 0;
    for (int s = 0; s < 64; s++) {
        if (g_board[s] == EMPTY_SQ) continue;
        int pw = (g_board[s] < 6) ? 1 : 0;
        int pt = g_board[s] % 6;
        int rc = (wp == pw) ? 0 : 1;
        int as = s;
        if (!wp) as ^= 56;
        if (m) as ^= 7;
        buf[cnt++] = rc * 384 + pt * 64 + as;
    }
    for (int i = 0; i < cnt - 1; i++)
        for (int j = i + 1; j < cnt; j++)
            if (buf[i] > buf[j]) {
                int tmp = buf[i]; buf[i] = buf[j]; buf[j] = tmp;
            }
    return cnt;
}

static void build_accumulator(int wp, int *acc) {
    int k = find_king(wp);
    int bk = wp ? k : (k ^ 56);
    int bu = BUCKET_MAP[bk];
    for (int h = 0; h < HIDDEN_SIZE; h++) acc[h] = g_ib[h];
    int fb[64];
    int nf = compute_features(wp, fb);
    for (int i = 0; i < nf; i++)
        for (int h = 0; h < HIDDEN_SIZE; h++)
            acc[h] += g_iw[bu][fb[i]][h];
}

static int activation(int x) {
    int c = x < 0 ? 0 : (x > QA ? QA : x);
    return c * c;
}

static int forward_pass(int *us, int *them) {
    int output = 0;
    for (int h = 0; h < HIDDEN_SIZE; h++) {
        output += activation(us[h]) * g_ow[h];
        output += activation(them[h]) * g_ow[HIDDEN_SIZE + h];
    }
    return (output / QA + g_ob) * SCALE / (QA * QB);
}

static int material_phase(void) {
    int phase = 0;
    for (int i = 0; i < 64; i++)
        if (g_board[i] != EMPTY_SQ) phase += PHASE_WT[g_board[i] % 6];
    return phase;
}

static int evaluate(void) {
    int wa[HIDDEN_SIZE], ba[HIDDEN_SIZE];
    build_accumulator(1, wa);
    build_accumulator(0, ba);
    int *us  = g_wtm ? wa : ba;
    int *them = g_wtm ? ba : wa;
    int ev = forward_pass(us, them);
    ev = ev * (22400 + material_phase()) / 32768;
    ev = ev * (200 - g_hmc) / 200;
    return ev;
}

int main(int argc, char **argv) {
    if (argc < 3) return 1;
    load_network();
    char fen[512] = "";
    for (int i = 2; i < argc; i++) {
        if (i > 2) strcat(fen, " ");
        strcat(fen, argv[i]);
    }
    parse_fen(fen);

    if (strcmp(argv[1], "eval") == 0) {
        printf("%d\n", evaluate());
    } else if (strcmp(argv[1], "features") == 0) {
        int wf[64], bf[64];
        int nw = compute_features(1, wf);
        int nb = compute_features(0, bf);
        printf("white:");
        for (int i = 0; i < nw; i++) printf(" %d", wf[i]);
        printf("\nblack:");
        for (int i = 0; i < nb; i++) printf(" %d", bf[i]);
        printf("\n");
    } else if (strcmp(argv[1], "probe") == 0) {
        printf("eval: %d\n", evaluate());
        int wf[64], bf[64];
        int nw = compute_features(1, wf);
        int nb = compute_features(0, bf);
        printf("white_features:");
        for (int i = 0; i < nw; i++) printf(" %d", wf[i]);
        printf("\nblack_features:");
        for (int i = 0; i < nb; i++) printf(" %d", bf[i]);
        printf("\n");
    }
    return 0;
}
