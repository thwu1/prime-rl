#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "graph.h"
#include "analytics.h"

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s <graph_file> <command> [args...]\n"
        "Commands:\n"
        "  bfs <source>\n"
        "  bc\n"
        "  pagerank <damping> <epsilon> <max_iter>\n", prog);
    exit(1);
}

int main(int argc, char *argv[]) {
    if (argc < 3) usage(argv[0]);

    Graph *g = graph_load(argv[1]);
    if (!g) { fprintf(stderr, "Error loading graph: %s\n", argv[1]); return 1; }

    if (strcmp(argv[2], "bfs") == 0) {
        if (argc < 4) usage(argv[0]);
        int source = atoi(argv[3]);
        int *distances = (int *)malloc(g->num_vertices * sizeof(int));
        bfs_distances(g, source, distances);
        for (int i = 0; i < g->num_vertices; i++)
            printf("%d %d\n", i, distances[i]);
        free(distances);

    } else if (strcmp(argv[2], "bc") == 0) {
        double *bc = (double *)calloc(g->num_vertices, sizeof(double));
        betweenness_centrality(g, bc);
        for (int i = 0; i < g->num_vertices; i++)
            printf("%d %.10f\n", i, bc[i]);
        free(bc);

    } else if (strcmp(argv[2], "pagerank") == 0) {
        if (argc < 6) usage(argv[0]);
        double damping  = atof(argv[3]);
        double epsilon  = atof(argv[4]);
        int    max_iter = atoi(argv[5]);
        double *pr = (double *)malloc(g->num_vertices * sizeof(double));
        pagerank(g, pr, damping, epsilon, max_iter);
        for (int i = 0; i < g->num_vertices; i++)
            printf("%d %.10f\n", i, pr[i]);
        free(pr);

    } else {
        usage(argv[0]);
    }

    graph_free(g);
    return 0;
}
