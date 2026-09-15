/*
 */

#ifndef ANALYTICS_H
#define ANALYTICS_H

#include "graph.h"

void bfs_distances(const Graph *g, int source, int *distances);
void betweenness_centrality(const Graph *g, double *bc);
void pagerank(const Graph *g, double *pr, double damping,
              double epsilon, int max_iter);

#endif /* ANALYTICS_H */
