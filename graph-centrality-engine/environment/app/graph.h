#ifndef GRAPH_H
#define GRAPH_H

typedef struct {
    int num_vertices;
    int num_edges;       /* number of directed edges */
    int *row_offsets;    /* CSR row offsets, size num_vertices + 1 */
    int *col_indices;    /* CSR column indices (outgoing neighbors), size num_edges */
    int *out_degree;     /* out-degree of each vertex, size num_vertices */
} Graph;

/*
 * Load a directed graph from an edge-list file.
 *
 * File format:
 *   Line 1: N M   (N vertices numbered 0..N-1, M directed edges)
 *   Lines 2..M+1: u v   (directed edge u -> v)
 *
 * Returns a heap-allocated Graph, or NULL on error.
 */
Graph *graph_load(const char *filename);

/* Free all memory associated with a graph. */
void graph_free(Graph *g);

#endif /* GRAPH_H */
