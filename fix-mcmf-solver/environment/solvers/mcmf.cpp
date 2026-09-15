// Min-Cost Max-Flow solver using SPFA
// Reads graph from stdin, outputs max_flow min_cost to stdout
// Input format: first line "n m s t", then m lines "u v cap cost"
#include <iostream>
#include <vector>
#include <deque>
#include <limits>
#include <algorithm>

using namespace std;

struct Edge {
    int from, to;
    long long cap, flow, cost;
};

int n;
vector<vector<int>> g;
vector<Edge> edges;

void add_edge(int from, int to, long long cap, long long cost) {
    g[from].push_back(edges.size());
    edges.push_back({from, to, cap, 0, cost});
    g[to].push_back(edges.size());
    edges.push_back({to, from, 0, 0, -cost});
}

pair<long long, long long> mcmf(int s, int t) {
    long long total_flow = 0, total_cost = 0;
    const long long INF = 1e18;

    while (true) {
        vector<long long> dist(n, INF);
        vector<bool> in_q(n, false);
        vector<int> pe(n, -1);

        dist[s] = 0;
        deque<int> q;
        q.push_back(s);
        in_q[s] = true;

        while (!q.empty()) {
            int v = q.front(); q.pop_front();
            in_q[v] = false;
            for (int id : g[v]) {
                Edge& e = edges[id];
                if (e.cap - e.flow > 0 && dist[v] + e.cost < dist[e.to]) {
                    dist[e.to] = dist[v] + e.cost;
                    pe[e.to] = id;
                    if (!in_q[e.to]) {
                        q.push_back(e.to);
                        in_q[e.to] = true;
                    }
                }
            }
        }

        if (dist[t] >= INF) break;

        long long push = INF;
        for (int v = t; v != s; v = edges[pe[v]].from)
            push = min(push, edges[pe[v]].cap - edges[pe[v]].flow);

        for (int v = t; v != s; v = edges[pe[v]].from) {
            edges[pe[v]].flow += push;
            edges[pe[v] ^ 1].flow -= push;
        }

        total_flow += push;
        total_cost += push * dist[t];
    }

    return {total_flow, total_cost};
}

int main() {
    int m, s, t;
    cin >> n >> m >> s >> t;
    g.resize(n);

    for (int i = 0; i < m; i++) {
        int u, v;
        long long cap, cost;
        cin >> u >> v >> cap >> cost;
        add_edge(u, v, cap, cost);
    }

    auto [flow, cost] = mcmf(s, t);
    cout << flow << " " << cost << endl;

    return 0;
}
