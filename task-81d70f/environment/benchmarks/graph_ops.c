/* Graph algorithms with CSR adjacency representation */

static int min_int(int a, int b) { return a < b ? a : b; }

void bfs_distances(const int *adj, const int *offsets, int n,
                   int src, int *dist) {
    int queue[1024];
    int front = 0, back = 0;
    for (int i = 0; i < n; i++) dist[i] = -1;
    dist[src] = 0;
    queue[back++] = src;
    while (front < back) {
        int u = queue[front++];
        for (int e = offsets[u]; e < offsets[u+1]; e++) {
            int v = adj[e];
            if (dist[v] == -1) {
                dist[v] = dist[u] + 1;
                queue[back++] = v;
            }
        }
    }
}

void dijkstra(const int *adj, const int *weights, const int *offsets,
              int n, int src, int *dist) {
    int visited[1024];
    for (int i = 0; i < n; i++) { dist[i] = 0x7FFFFFFF; visited[i] = 0; }
    dist[src] = 0;
    for (int iter = 0; iter < n; iter++) {
        int u = -1, best = 0x7FFFFFFF;
        for (int v = 0; v < n; v++)
            if (!visited[v] && dist[v] < best) { best = dist[v]; u = v; }
        if (u == -1) break;
        visited[u] = 1;
        for (int e = offsets[u]; e < offsets[u+1]; e++) {
            int v = adj[e], w = weights[e];
            int nd = dist[u] + w;
            if (nd < dist[v]) dist[v] = nd;
        }
    }
}

int connected_components(const int *adj, const int *offsets, int n, int *comp) {
    for (int i = 0; i < n; i++) comp[i] = -1;
    int nc = 0;
    int stack[1024];
    for (int i = 0; i < n; i++) {
        if (comp[i] != -1) continue;
        int top = 0;
        stack[top++] = i;
        while (top > 0) {
            int u = stack[--top];
            if (comp[u] != -1) continue;
            comp[u] = nc;
            for (int e = offsets[u]; e < offsets[u+1]; e++) {
                int v = adj[e];
                if (comp[v] == -1) stack[top++] = v;
            }
        }
        nc++;
    }
    return nc;
}

void floyd_warshall(int *dist, int n) {
    for (int k = 0; k < n; k++)
        for (int i = 0; i < n; i++)
            for (int j = 0; j < n; j++) {
                int via = dist[i*n+k] + dist[k*n+j];
                dist[i*n+j] = min_int(dist[i*n+j], via);
            }
}

void bellman_ford(const int *src_arr, const int *dst_arr, const int *w_arr,
                  int num_edges, int n, int source, int *dist) {
    for (int i = 0; i < n; i++) dist[i] = 0x7FFFFFFF;
    dist[source] = 0;
    for (int round = 0; round < n - 1; round++) {
        for (int e = 0; e < num_edges; e++) {
            int u = src_arr[e], v = dst_arr[e], w = w_arr[e];
            if (dist[u] != 0x7FFFFFFF) {
                int nd = dist[u] + w;
                if (nd < dist[v]) dist[v] = nd;
            }
        }
    }
}
