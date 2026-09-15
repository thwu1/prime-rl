//
// Optimal twinwidth solver using branch-and-bound with greedy upper bound,
// twin detection, and bidirectional contraction exploration.
//
// Compiled with: g++ -O2 -std=c++17 -o solver solver.cpp

#include <iostream>
#include <vector>
#include <string>
#include <algorithm>
#include <cstring>
#include <sstream>
using namespace std;

const int MAXN = 55;

struct State {
    int n;
    bool alive[MAXN];
    // adj[u][v]: 0 = no edge, 1 = black, 2 = red
    int adj[MAXN][MAXN];
    int nalive;

    void init(int nn, const vector<pair<int,int>>& edges) {
        n = nn;
        nalive = nn;
        memset(alive, 0, sizeof(alive));
        memset(adj, 0, sizeof(adj));
        for (int i = 1; i <= n; i++) alive[i] = true;
        for (auto& [u, v] : edges) {
            adj[u][v] = adj[v][u] = 1; // black
        }
    }

    void contract(int x, int y) {
        // Contract y into x: x survives, y removed
        // For each z != x,y that is alive:
        //   if z adj to both x and y: keep x's color
        //   if z adj to x only: make red
        //   if z adj to y only: new red
        for (int z = 1; z <= n; z++) {
            if (!alive[z] || z == x || z == y) continue;
            bool xa = adj[x][z] > 0;
            bool ya = adj[y][z] > 0;
            if (xa && ya) {
                // keep x's current color — no change needed
            } else if (xa && !ya) {
                adj[x][z] = adj[z][x] = 2; // red
            } else if (!xa && ya) {
                adj[x][z] = adj[z][x] = 2; // new red
            }
            // else: neither adjacent, no edge
        }
        // Remove y
        alive[y] = false;
        nalive--;
        for (int z = 1; z <= n; z++) {
            adj[y][z] = adj[z][y] = 0;
        }
    }

    int maxRedDeg() const {
        int mx = 0;
        for (int v = 1; v <= n; v++) {
            if (!alive[v]) continue;
            int rd = 0;
            for (int u = 1; u <= n; u++) {
                if (alive[u] && adj[v][u] == 2) rd++;
            }
            mx = max(mx, rd);
        }
        return mx;
    }

    // Check if u and v are twins (same open neighborhood ignoring colors)
    bool areTwins(int u, int v) const {
        for (int z = 1; z <= n; z++) {
            if (!alive[z] || z == u || z == v) continue;
            if ((adj[u][z] > 0) != (adj[v][z] > 0)) return false;
        }
        return true;
    }
};

int N;
int bestWidth;
vector<pair<int,int>> bestSeq;

void search(State& s, int curWidth, vector<pair<int,int>>& seq) {
    if (s.nalive == 1) {
        if (curWidth < bestWidth) {
            bestWidth = curWidth;
            bestSeq = seq;
        }
        return;
    }
    if (curWidth >= bestWidth) return;

    // Try twin contractions first (always optimal — no width increase)
    for (int i = 1; i <= N; i++) {
        if (!s.alive[i]) continue;
        for (int j = i + 1; j <= N; j++) {
            if (!s.alive[j]) continue;
            if (s.areTwins(i, j)) {
                State ns = s;
                ns.contract(i, j);
                int w = max(curWidth, ns.maxRedDeg());
                if (w < bestWidth) {
                    seq.push_back({i, j});
                    search(ns, w, seq);
                    seq.pop_back();
                }
                return; // Twins are interchangeable; one branch suffices
            }
        }
    }

    // No twins found — try all ordered pairs
    for (int i = 1; i <= N; i++) {
        if (!s.alive[i]) continue;
        for (int j = i + 1; j <= N; j++) {
            if (!s.alive[j]) continue;

            // Direction 1: contract j into i (i survives)
            {
                State ns = s;
                ns.contract(i, j);
                int w = max(curWidth, ns.maxRedDeg());
                if (w < bestWidth) {
                    seq.push_back({i, j});
                    search(ns, w, seq);
                    seq.pop_back();
                }
            }

            // Direction 2: contract i into j (j survives)
            {
                State ns = s;
                ns.contract(j, i);
                int w = max(curWidth, ns.maxRedDeg());
                if (w < bestWidth) {
                    seq.push_back({j, i});
                    search(ns, w, seq);
                    seq.pop_back();
                }
            }
        }
    }
}

void greedy(const State& initial) {
    State s = initial;
    bestWidth = 0;
    bestSeq.clear();

    while (s.nalive > 1) {
        int bw = 1 << 30;
        int bx = -1, by = -1;

        // Check twins first
        bool found_twin = false;
        for (int i = 1; i <= N && !found_twin; i++) {
            if (!s.alive[i]) continue;
            for (int j = i + 1; j <= N && !found_twin; j++) {
                if (!s.alive[j]) continue;
                if (s.areTwins(i, j)) {
                    State ns = s;
                    ns.contract(i, j);
                    bw = ns.maxRedDeg();
                    bx = i; by = j;
                    found_twin = true;
                }
            }
        }

        if (!found_twin) {
            // Try all pairs, both directions
            for (int i = 1; i <= N; i++) {
                if (!s.alive[i]) continue;
                for (int j = i + 1; j <= N; j++) {
                    if (!s.alive[j]) continue;
                    // i survives
                    {
                        State ns = s;
                        ns.contract(i, j);
                        int w = ns.maxRedDeg();
                        if (w < bw) { bw = w; bx = i; by = j; }
                    }
                    // j survives
                    {
                        State ns = s;
                        ns.contract(j, i);
                        int w = ns.maxRedDeg();
                        if (w < bw) { bw = w; bx = j; by = i; }
                    }
                }
            }
        }

        s.contract(bx, by);
        bestWidth = max(bestWidth, bw);
        bestSeq.push_back({bx, by});
    }
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int n = 0, m = 0;
    vector<pair<int,int>> edges;
    string line;

    while (getline(cin, line)) {
        if (line.empty() || line[0] == 'c') continue;
        if (line[0] == 'p') {
            sscanf(line.c_str(), "p tww %d %d", &n, &m);
        } else {
            int u, v;
            if (sscanf(line.c_str(), "%d %d", &u, &v) == 2) {
                edges.push_back({u, v});
            }
        }
    }

    if (n <= 1) {
        // No contractions needed
        return 0;
    }

    N = n;
    State initial;
    initial.init(n, edges);

    // Phase 1: greedy upper bound
    greedy(initial);

    // Phase 2: branch-and-bound improvement
    if (bestWidth > 0) {
        vector<pair<int,int>> seq;
        search(initial, 0, seq);
    }

    // Output best sequence found
    for (auto& [x, y] : bestSeq) {
        cout << x << " " << y << "\n";
    }

    return 0;
}
