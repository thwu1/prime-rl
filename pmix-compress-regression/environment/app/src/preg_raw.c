/*
 * Raw text PPN encoding backend.
 * Format: "raw:r0,r1,...;r4,r5,..."
 *
 * Ranks within a node are comma-separated; nodes are semicolon-separated.
 */

#include "preg.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

int preg_raw_generate(const pmix_proc_map_t *map,
                      char **output, size_t *outlen)
{
    /* Estimate buffer size: each rank takes up to 7 digits + separator */
    size_t bufsz = 8 + (size_t)map->nprocs * 8;
    char *buf = (char *)malloc(bufsz);
    if (!buf) return -1;

    int pos = sprintf(buf, "raw:");

    for (int n = 0; n < map->nnodes; n++) {
        if (n > 0) {
            buf[pos++] = ';';
        }
        for (int r = 0; r < map->nodes[n].nranks; r++) {
            if (r > 0) {
                buf[pos++] = ',';
            }
            pos += sprintf(buf + pos, "%d", map->nodes[n].ranks[r]);
            /* Grow buffer if approaching capacity */
            if ((size_t)(pos + 16) >= bufsz) {
                bufsz *= 2;
                char *tmp = (char *)realloc(buf, bufsz);
                if (!tmp) { free(buf); return -1; }
                buf = tmp;
            }
        }
    }
    buf[pos] = '\0';

    *output = buf;
    *outlen = (size_t)pos;
    return 0;
}

int preg_raw_parse(const char *input, size_t inlen,
                   pmix_proc_map_t *map)
{
    const char *data = input + 4;  /* skip "raw:" */
    size_t dlen = inlen - 4;

    /* Count nodes: number of semicolons + 1 */
    int nnodes = 1;
    for (size_t i = 0; i < dlen; i++) {
        if (data[i] == ';') nnodes++;
    }

    map->nodes = (pmix_node_map_t *)calloc(nnodes, sizeof(pmix_node_map_t));
    if (!map->nodes) return -1;
    map->nnodes = nnodes;
    map->nprocs = 0;

    /* Parse each node's comma-separated rank list */
    char *copy = strndup(data, dlen);
    if (!copy) { free(map->nodes); map->nodes = NULL; return -1; }

    char *saveptr_node = NULL;
    char *node_tok = strtok_r(copy, ";", &saveptr_node);

    for (int n = 0; n < nnodes && node_tok; n++) {
        /* Count commas to determine rank count on this node */
        int nranks = 1;
        for (char *p = node_tok; *p; p++) {
            if (*p == ',') nranks++;
        }

        map->nodes[n].ranks = (int *)calloc(nranks, sizeof(int));
        if (!map->nodes[n].ranks) {
            free(copy);
            return -1;
        }
        map->nodes[n].nranks = nranks;
        map->nprocs += nranks;

        char *saveptr_rank = NULL;
        char *rank_tok = strtok_r(node_tok, ",", &saveptr_rank);
        for (int r = 0; r < nranks && rank_tok; r++) {
            map->nodes[n].ranks[r] = atoi(rank_tok);
            rank_tok = strtok_r(NULL, ",", &saveptr_rank);
        }

        node_tok = strtok_r(NULL, ";", &saveptr_node);
    }

    free(copy);
    return 0;
}
