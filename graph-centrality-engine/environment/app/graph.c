#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "graph.h"

Graph *graph_load(const char *filename) {
    FILE *f = fopen(filename, "r");
    if (!f) return NULL;

    int n, m;
    if (fscanf(f, "%d %d", &n, &m) != 2) { fclose(f); return NULL; }

    int *src = (int *)malloc(m * sizeof(int));
    int *dst = (int *)malloc(m * sizeof(int));
    if (!src || !dst) { free(src); free(dst); fclose(f); return NULL; }

    for (int i = 0; i < m; i++) {
        if (fscanf(f, "%d %d", &src[i], &dst[i]) != 2) {
            free(src); free(dst); fclose(f); return NULL;
        }
    }
    fclose(f);

    Graph *g = (Graph *)malloc(sizeof(Graph));
    g->num_vertices = n;
    g->num_edges    = m;
    g->row_offsets  = (int *)calloc(n + 1, sizeof(int));
    g->col_indices  = (int *)malloc(m * sizeof(int));
    g->out_degree   = (int *)calloc(n, sizeof(int));

    for (int i = 0; i < m; i++)
        g->out_degree[src[i]]++;

    for (int i = 0; i < n; i++)
        g->row_offsets[i + 1] = g->row_offsets[i] + g->out_degree[i];

    int *pos = (int *)calloc(n, sizeof(int));
    for (int i = 0; i < m; i++) {
        int u   = src[i];
        int idx = g->row_offsets[u] + pos[u];
        g->col_indices[idx] = dst[i];
        pos[u]++;
    }

    free(src); free(dst); free(pos);
    return g;
}

void graph_free(Graph *g) {
    if (!g) return;
    free(g->row_offsets);
    free(g->col_indices);
    free(g->out_degree);
    free(g);
}
