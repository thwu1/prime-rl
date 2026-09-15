/*
 * BPE encoder — reads a binary model file and performs greedy BPE encoding.
 * Uses POSIX I/O (open/read/lseek) for model loading so that system-call
 * traces clearly reveal the file format structure.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>

#define MAX_MERGES 4096
#define BASE_VOCAB 256

typedef struct { uint16_t p0, p1; } MergePair;

static MergePair mt[MAX_MERGES];
static int nm = 0;
static uint8_t *tb[BASE_VOCAB + MAX_MERGES];
static int tl[BASE_VOCAB + MAX_MERGES];

static void build_vocab(void) {
    int i;
    for (i = 0; i < BASE_VOCAB; i++) {
        tb[i] = (uint8_t *)malloc(1);
        tb[i][0] = (uint8_t)i;
        tl[i] = 1;
    }
    for (i = 0; i < nm; i++) {
        int id = BASE_VOCAB + i;
        int a = mt[i].p0, b = mt[i].p1;
        tl[id] = tl[a] + tl[b];
        tb[id] = (uint8_t *)malloc(tl[id]);
        memcpy(tb[id], tb[a], tl[a]);
        memcpy(tb[id] + tl[a], tb[b], tl[b]);
    }
}

static int load_model(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror("open"); return -1; }

    char magic[4];
    if (read(fd, magic, 4) != 4 || memcmp(magic, "BPE1", 4) != 0) {
        fprintf(stderr, "error: bad magic\n");
        close(fd); return -1;
    }

    uint8_t ver;
    if (read(fd, &ver, 1) != 1 || ver != 1) {
        fprintf(stderr, "error: unsupported version\n");
        close(fd); return -1;
    }

    uint16_t n;
    read(fd, &n, 2);
    nm = n;

    uint32_t off;
    read(fd, &off, 4);

    lseek(fd, (off_t)off, SEEK_SET);

    read(fd, mt, nm * sizeof(MergePair));
    close(fd);

    build_vocab();
    return 0;
}

static void do_encode(const char *text) {
    int len = (int)strlen(text);
    if (len == 0) { printf("\n"); return; }

    int *ids = (int *)malloc(len * sizeof(int));
    int i;
    for (i = 0; i < len; i++) ids[i] = (uint8_t)text[i];

    while (len >= 2) {
        int best = nm;
        for (i = 0; i < len - 1; i++) {
            int r;
            for (r = 0; r < nm; r++) {
                if (mt[r].p0 == ids[i] && mt[r].p1 == ids[i+1]) {
                    if (r < best) best = r;
                    break;
                }
            }
        }
        if (best >= nm) break;
        int nid = BASE_VOCAB + best;
        int *tmp = (int *)malloc(len * sizeof(int));
        int nl = 0;
        i = 0;
        while (i < len) {
            if (i < len-1 && ids[i]==mt[best].p0 && ids[i+1]==mt[best].p1)
                { tmp[nl++] = nid; i += 2; }
            else { tmp[nl++] = ids[i]; i++; }
        }
        free(ids); ids = tmp; len = nl;
    }
    for (i = 0; i < len; i++) { if (i) printf(" "); printf("%d", ids[i]); }
    printf("\n");
    free(ids);
}

static void do_decode(int ac, char **av) {
    int i;
    for (i = 0; i < ac; i++) {
        int id = atoi(av[i]);
        if (id < 0 || id >= BASE_VOCAB + nm) {
            fprintf(stderr, "error: invalid token %d\n", id);
            return;
        }
        fwrite(tb[id], 1, tl[id], stdout);
    }
    printf("\n");
}

int main(int argc, char *argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <model> <encode|decode|info> [args...]\n", argv[0]);
        return 1;
    }
    if (load_model(argv[1]) != 0) return 1;

    if (strcmp(argv[2], "info") == 0) {
        printf("format: BPE1\nmerges: %d\nvocab_size: %d\n", nm, BASE_VOCAB+nm);
    } else if (strcmp(argv[2], "encode") == 0) {
        if (argc < 4) { fprintf(stderr, "encode: need text\n"); return 1; }
        do_encode(argv[3]);
    } else if (strcmp(argv[2], "decode") == 0) {
        if (argc < 4) { fprintf(stderr, "decode: need ids\n"); return 1; }
        do_decode(argc-3, argv+3);
    } else {
        fprintf(stderr, "error: unknown command '%s'\n", argv[2]);
        return 1;
    }
    return 0;
}
