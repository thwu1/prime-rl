#ifndef ANALYTICS_H
#define ANALYTICS_H

#include "graph.h"

/*
 * Compute single-source shortest-path distances using BFS.
 *
 * Parameters:
 *   g         - pointer to the directed graph (CSR, outgoing edges only)
 *   source    - source vertex (0-indexed)
 *   distances - caller-allocated array of size g->num_vertices;
 *               on return, distances[v] = shortest distance from source to v,
 *               or -1 if v is unreachable from source
 */
void bfs_distances(const Graph *g, int source, int *distances);

/*
 * Compute unnormalized betweenness centrality for every vertex
 * using Brandes' algorithm on a directed graph.
 *
 *   BC(v) = sum_{s != v != t}  sigma_st(v) / sigma_st
 *
 * where sigma_st is the total number of shortest paths from s to t,
 * and sigma_st(v) is the number of those paths passing through v.
 *
 * Parameters:
 *   g  - pointer to the directed graph
 *   bc - caller-allocated array of size g->num_vertices
 *        (will be filled with betweenness centrality values)
 */
void betweenness_centrality(const Graph *g, double *bc);

/*
 * Compute PageRank for every vertex using the iterative power method.
 *
 * Dangling nodes (vertices with out-degree 0) redistribute their rank
 * uniformly across ALL vertices each iteration.
 *
 * Convergence criterion: stop when the L1 norm of the difference
 * between consecutive rank vectors is less than epsilon,
 * or after max_iter iterations, whichever comes first.
 *
 * Parameters:
 *   g        - pointer to the directed graph
 *   pr       - caller-allocated array of size g->num_vertices
 *   damping  - damping factor (typically 0.85)
 *   epsilon  - convergence threshold for L1 norm
 *   max_iter - maximum number of iterations
 */
void pagerank(const Graph *g, double *pr, double damping,
              double epsilon, int max_iter);

#endif /* ANALYTICS_H */
