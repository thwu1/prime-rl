/*
 * Reference solution for the graph centrality engine task.
 *
 */

#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "analytics.h"

/* ------------------------------------------------------------------ */
/*  BFS                                                                */
/* ------------------------------------------------------------------ */

void bfs_distances(const Graph *g, int source, int *distances) {
    int n = g->num_vertices;
    for (int i = 0; i < n; i++) distances[i] = -1;

    int *queue = (int *)malloc(n * sizeof(int));
    int front = 0, back = 0;

    distances[source] = 0;
    queue[back++] = source;

    while (front < back) {
        int u = queue[front++];
        for (int j = g->row_offsets[u]; j < g->row_offsets[u + 1]; j++) {
            int v = g->col_indices[j];
            if (distances[v] < 0) {
                distances[v] = distances[u] + 1;
                queue[back++] = v;
            }
        }
    }
    free(queue);
}

/* ------------------------------------------------------------------ */
/*  Betweenness Centrality  (Brandes' algorithm)                       */
/* ------------------------------------------------------------------ */

void betweenness_centrality(const Graph *g, double *bc) {
    int n = g->num_vertices;
    memset(bc, 0, n * sizeof(double));

    /* per-source scratch space */
    int    *S     = (int *)   malloc(n * sizeof(int));     /* stack  */
    int    *Q     = (int *)   malloc(n * sizeof(int));     /* queue  */
    int    *dist  = (int *)   malloc(n * sizeof(int));
    double *sigma = (double *)malloc(n * sizeof(double));
    double *delta = (double *)malloc(n * sizeof(double));

    /* predecessor lists  (variable-length per vertex) */
    int **P     = (int **)malloc(n * sizeof(int *));
    int  *P_cnt = (int *) malloc(n * sizeof(int));
    int  *P_cap = (int *) malloc(n * sizeof(int));

    for (int s = 0; s < n; s++) {
        /* --- initialise --- */
        int S_top = 0, Q_front = 0, Q_back = 0;
        for (int i = 0; i < n; i++) {
            P[i] = NULL;  P_cnt[i] = 0;  P_cap[i] = 0;
            dist[i]  = -1;
            sigma[i] = 0.0;
            delta[i] = 0.0;
        }
        dist[s]  = 0;
        sigma[s] = 1.0;
        Q[Q_back++] = s;

        /* --- forward BFS pass --- */
        while (Q_front < Q_back) {
            int v = Q[Q_front++];
            S[S_top++] = v;
            for (int j = g->row_offsets[v]; j < g->row_offsets[v + 1]; j++) {
                int w = g->col_indices[j];
                /* first discovery */
                if (dist[w] < 0) {
                    dist[w] = dist[v] + 1;
                    Q[Q_back++] = w;
                }
                /* w is one hop farther than v => v is a predecessor of w */
                if (dist[w] == dist[v] + 1) {
                    sigma[w] += sigma[v];
                    /* append v to P[w] */
                    if (P_cnt[w] >= P_cap[w]) {
                        P_cap[w] = (P_cap[w] == 0) ? 4 : P_cap[w] * 2;
                        P[w] = (int *)realloc(P[w], P_cap[w] * sizeof(int));
                    }
                    P[w][P_cnt[w]++] = v;
                }
            }
        }

        /* --- backward dependency accumulation --- */
        while (S_top > 0) {
            int w = S[--S_top];
            for (int j = 0; j < P_cnt[w]; j++) {
                int v = P[w][j];
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w]);
            }
            if (w != s) {
                bc[w] += delta[w];
            }
        }

        /* free predecessor lists for this source */
        for (int i = 0; i < n; i++) free(P[i]);
    }

    free(S); free(Q); free(dist); free(sigma); free(delta);
    free(P); free(P_cnt); free(P_cap);
}

/* ------------------------------------------------------------------ */
/*  PageRank  (push-based power iteration)                             */
/* ------------------------------------------------------------------ */

void pagerank(const Graph *g, double *pr, double damping,
              double epsilon, int max_iter) {
    int n = g->num_vertices;
    double inv_n = 1.0 / n;
    double *new_pr = (double *)malloc(n * sizeof(double));

    /* uniform initialisation */
    for (int i = 0; i < n; i++) pr[i] = inv_n;

    for (int iter = 0; iter < max_iter; iter++) {
        /* dangling-node rank mass */
        double dangling = 0.0;
        for (int i = 0; i < n; i++) {
            if (g->out_degree[i] == 0)
                dangling += pr[i];
        }

        /* base rank for every vertex: teleport + dangling redistribution */
        double base = (1.0 - damping) * inv_n + damping * dangling * inv_n;
        for (int i = 0; i < n; i++) new_pr[i] = base;

        /* push rank along outgoing edges */
        for (int u = 0; u < n; u++) {
            if (g->out_degree[u] == 0) continue;
            double contrib = damping * pr[u] / g->out_degree[u];
            for (int j = g->row_offsets[u]; j < g->row_offsets[u + 1]; j++) {
                new_pr[g->col_indices[j]] += contrib;
            }
        }

        /* convergence check (L1 norm) */
        double diff = 0.0;
        for (int i = 0; i < n; i++) diff += fabs(new_pr[i] - pr[i]);
        memcpy(pr, new_pr, n * sizeof(double));
        if (diff < epsilon) break;
    }

    free(new_pr);
}
