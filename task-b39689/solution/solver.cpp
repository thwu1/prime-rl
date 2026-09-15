/*
 * Sokoban Solver: A* search with dead-square pruning and Hungarian heuristic.
 * Reads an XSB puzzle file, outputs a LURD solution string.
 *
 */
#include <algorithm>
#include <cassert>
#include <climits>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <queue>
#include <string>
#include <unordered_map>
#include <vector>

using namespace std;

static constexpr int MX  = 22;      // max board dimension
static constexpr int MXB = 8;       // max boxes supported

static const int DR[] = {-1, 1, 0, 0};   // up, down, left, right
static const int DC[] = {0, 0, -1, 1};
static const char WCH[] = {'u', 'd', 'l', 'r'};   // walk chars
static const char PCH[] = {'U', 'D', 'L', 'R'};   // push chars

// --------------- Board ---------------

struct Board {
    int R = 0, C = 0, pr = 0, pc = 0;
    vector<pair<int,int>> ibox, goal;
    bool w[MX][MX]{};    // walls
    bool gm[MX][MX]{};   // goal map
    bool dead[MX][MX]{}; // dead squares
};

static inline bool inb(int r, int c, int R, int C) {
    return r >= 0 && r < R && c >= 0 && c < C;
}

static Board parse(const char* path) {
    Board b;
    ifstream fin(path);
    if (!fin) { cerr << "Cannot open " << path << "\n"; exit(1); }

    vector<string> lines;
    string ln;
    bool started = false;
    while (getline(fin, ln)) {
        while (!ln.empty() && (ln.back() == '\r' || ln.back() == '\n'))
            ln.pop_back();
        if (!ln.empty() && ln[0] == ';') continue;
        if (ln.empty()) { if (started) break; continue; }
        started = true;
        lines.push_back(ln);
    }

    b.R = (int)lines.size();
    for (auto& l : lines) b.C = max(b.C, (int)l.size());

    for (int r = 0; r < b.R; r++)
        for (int c = 0; c < b.C; c++) {
            char ch = c < (int)lines[r].size() ? lines[r][c] : ' ';
            if      (ch == '#') { b.w[r][c] = true; }
            else if (ch == '@') { b.pr = r; b.pc = c; }
            else if (ch == '+') { b.pr = r; b.pc = c;
                                  b.goal.push_back({r,c}); b.gm[r][c] = true; }
            else if (ch == '$') { b.ibox.push_back({r,c}); }
            else if (ch == '*') { b.ibox.push_back({r,c});
                                  b.goal.push_back({r,c}); b.gm[r][c] = true; }
            else if (ch == '.') { b.goal.push_back({r,c}); b.gm[r][c] = true; }
        }

    sort(b.ibox.begin(), b.ibox.end());
    sort(b.goal.begin(), b.goal.end());
    return b;
}

// --------------- Dead-square detection ---------------

static void compute_dead(Board& b) {
    // 1) Corner dead squares: non-goal cells with wall/edge on both axes
    for (int r = 0; r < b.R; r++)
        for (int c = 0; c < b.C; c++) {
            if (b.w[r][c] || b.gm[r][c]) continue;
            bool wv = (!inb(r-1,c,b.R,b.C) || b.w[r-1][c]) ||
                      (!inb(r+1,c,b.R,b.C) || b.w[r+1][c]);
            bool wh = (!inb(r,c-1,b.R,b.C) || b.w[r][c-1]) ||
                      (!inb(r,c+1,b.R,b.C) || b.w[r][c+1]);
            if (wv && wh) b.dead[r][c] = true;
        }

    // 2) Horizontal dead walls: segments along a wall with no goals, blocked ends
    for (int r = 0; r < b.R; r++)
        for (int side = 0; side < 2; side++) {
            int wr = r + (side ? 1 : -1);
            if (!inb(wr, 0, b.R, b.C)) continue;
            int c = 0;
            while (c < b.C) {
                if (b.w[r][c] || !b.w[wr][c]) { c++; continue; }
                int s = c;
                bool has_goal = false;
                while (c < b.C && !b.w[r][c] && b.w[wr][c]) {
                    if (b.gm[r][c]) has_goal = true;
                    c++;
                }
                if (!has_goal) {
                    bool lb = b.dead[r][s] || s == 0 || b.w[r][s-1];
                    bool rb = b.dead[r][c-1] || c >= b.C || b.w[r][c];
                    if (lb && rb)
                        for (int i = s; i < c; i++)
                            if (!b.gm[r][i]) b.dead[r][i] = true;
                }
            }
        }

    // 3) Vertical dead walls
    for (int c = 0; c < b.C; c++)
        for (int side = 0; side < 2; side++) {
            int wc = c + (side ? 1 : -1);
            if (!inb(0, wc, b.R, b.C)) continue;
            int r = 0;
            while (r < b.R) {
                if (b.w[r][c] || !b.w[r][wc]) { r++; continue; }
                int s = r;
                bool has_goal = false;
                while (r < b.R && !b.w[r][c] && b.w[r][wc]) {
                    if (b.gm[r][c]) has_goal = true;
                    r++;
                }
                if (!has_goal) {
                    bool tb = b.dead[s][c] || s == 0 || b.w[s-1][c];
                    bool bb = b.dead[r-1][c] || r >= b.R || b.w[r][c];
                    if (tb && bb)
                        for (int i = s; i < r; i++)
                            if (!b.gm[i][c]) b.dead[i][c] = true;
                }
            }
        }
}

// --------------- State representation ---------------

struct State {
    uint16_t bx[MXB]{};   // sorted encoded box positions (row*MX + col)
    uint16_t pz = 0;      // canonical player zone representative
    uint8_t  nb = 0;      // number of boxes

    bool operator==(const State& o) const {
        return pz == o.pz && nb == o.nb && memcmp(bx, o.bx, nb * 2) == 0;
    }
};

struct SHash {
    size_t operator()(const State& s) const {
        size_t h = (size_t)s.pz * 2654435761ULL;
        for (int i = 0; i < s.nb; i++)
            h ^= ((size_t)s.bx[i] * 2246822519ULL) +
                 0x9e3779b9ULL + (h << 6) + (h >> 2);
        return h;
    }
};

// --------------- Player zone (canonical reachable zone rep) ---------------

static uint16_t player_zone(int pr, int pc, const bool bm[][MX],
                             int R, int C, const bool w[][MX]) {
    bool vis[MX][MX]{};
    queue<int> q;
    q.push(pr * MX + pc);
    vis[pr][pc] = true;
    uint16_t mn = (uint16_t)(pr * MX + pc);

    while (!q.empty()) {
        int p = q.front(); q.pop();
        int r = p / MX, c = p % MX;
        for (int d = 0; d < 4; d++) {
            int nr = r + DR[d], nc = c + DC[d];
            if (!inb(nr, nc, R, C) || w[nr][nc] || vis[nr][nc] || bm[nr][nc])
                continue;
            vis[nr][nc] = true;
            uint16_t v = (uint16_t)(nr * MX + nc);
            if (v < mn) mn = v;
            q.push(v);
        }
    }
    return mn;
}

// --------------- BFS path for LURD reconstruction ---------------

static string bfs_path(int sr, int sc, int tr, int tc,
                        const bool bm[][MX], int R, int C, const bool w[][MX]) {
    if (sr == tr && sc == tc) return "";

    bool vis[MX][MX]{};
    int from[MX][MX], fd[MX][MX];
    memset(from, -1, sizeof from);
    memset(fd, -1, sizeof fd);

    queue<int> q;
    q.push(sr * MX + sc);
    vis[sr][sc] = true;

    while (!q.empty()) {
        int p = q.front(); q.pop();
        int r = p / MX, c = p % MX;
        for (int d = 0; d < 4; d++) {
            int nr = r + DR[d], nc = c + DC[d];
            if (!inb(nr, nc, R, C) || w[nr][nc] || vis[nr][nc] || bm[nr][nc])
                continue;
            vis[nr][nc] = true;
            from[nr][nc] = p;
            fd[nr][nc] = d;
            if (nr == tr && nc == tc) {
                string path;
                int cr = tr, cc = tc;
                while (cr != sr || cc != sc) {
                    path += WCH[fd[cr][cc]];
                    int pv = from[cr][cc];
                    cr = pv / MX; cc = pv % MX;
                }
                reverse(path.begin(), path.end());
                return path;
            }
            q.push(nr * MX + nc);
        }
    }
    return "";
}

// --------------- Heuristic: min-cost assignment (bitmask DP) ---------------

static int h_assign(const State& s, const vector<pair<int,int>>& goals) {
    int n = s.nb;
    if (n == 0) return 0;

    int dist[MXB][MXB];
    for (int i = 0; i < n; i++) {
        int br = s.bx[i] / MX, bc = s.bx[i] % MX;
        for (int j = 0; j < n; j++)
            dist[i][j] = abs(br - goals[j].first) + abs(bc - goals[j].second);
    }

    int full = (1 << n) - 1;
    vector<int> dp(full + 1, INT_MAX);
    dp[0] = 0;
    for (int mask = 0; mask <= full; mask++) {
        if (dp[mask] == INT_MAX) continue;
        int i = __builtin_popcount(mask);
        if (i >= n) continue;
        for (int j = 0; j < n; j++) {
            if (mask & (1 << j)) continue;
            int nm = mask | (1 << j);
            int v = dp[mask] + dist[i][j];
            if (v < dp[nm]) dp[nm] = v;
        }
    }
    return dp[full];
}

// --------------- Closed/Open nodes ---------------

struct CNode {
    State st;
    int16_t pr, pc;
    int par;       // index in closed list (-1 for root)
    int8_t pd;     // push direction (-1 for root)
};

struct OEntry {
    State st;
    int16_t pr, pc;
    int g, f;
    int par;
    int8_t pd;
    bool operator>(const OEntry& o) const { return f > o.f; }
};

// --------------- Solve ---------------

static string solve(Board& b) {
    compute_dead(b);
    int nb = (int)b.ibox.size();

    // Encode goal positions
    vector<uint16_t> genc;
    for (auto& [r, c] : b.goal)
        genc.push_back((uint16_t)(r * MX + c));
    sort(genc.begin(), genc.end());

    // Build initial state
    State s0{};
    s0.nb = (uint8_t)nb;
    bool bm0[MX][MX]{};
    for (int i = 0; i < nb; i++) {
        s0.bx[i] = (uint16_t)(b.ibox[i].first * MX + b.ibox[i].second);
        bm0[b.ibox[i].first][b.ibox[i].second] = true;
    }
    sort(s0.bx, s0.bx + nb);
    s0.pz = player_zone(b.pr, b.pc, bm0, b.R, b.C, b.w);

    // Already solved?
    {
        bool ok = true;
        for (int i = 0; i < nb; i++)
            if (!binary_search(genc.begin(), genc.end(), s0.bx[i]))
                { ok = false; break; }
        if (ok) return "x";
    }

    // A* search
    vector<CNode> cl;   // closed list
    priority_queue<OEntry, vector<OEntry>, greater<OEntry>> pq;
    unordered_map<State, int, SHash> bg;   // best g-value per state

    int h0 = h_assign(s0, b.goal);
    OEntry o0{};
    o0.st = s0; o0.pr = (int16_t)b.pr; o0.pc = (int16_t)b.pc;
    o0.g = 0; o0.f = h0; o0.par = -1; o0.pd = -1;
    pq.push(o0);
    bg[s0] = 0;

    while (!pq.empty()) {
        OEntry cur = pq.top(); pq.pop();

        // Skip stale entries
        { auto it = bg.find(cur.st);
          if (it != bg.end() && it->second < cur.g) continue; }

        int ci = (int)cl.size();
        cl.push_back({cur.st, cur.pr, cur.pc, cur.par, cur.pd});

        // Check if solved
        {
            bool ok = true;
            for (int i = 0; i < nb; i++)
                if (!binary_search(genc.begin(), genc.end(), cur.st.bx[i]))
                    { ok = false; break; }
            if (ok) {
                // Reconstruct LURD path via parent chain
                vector<int> chain;
                for (int x = ci; x >= 0; x = cl[x].par)
                    chain.push_back(x);
                reverse(chain.begin(), chain.end());

                string result;
                for (int k = 1; k < (int)chain.size(); k++) {
                    auto& prv = cl[chain[k-1]];
                    auto& cur2 = cl[chain[k]];
                    int d = cur2.pd;

                    // Build parent's box map
                    bool pbm[MX][MX]{};
                    for (int i = 0; i < nb; i++)
                        pbm[prv.st.bx[i] / MX][prv.st.bx[i] % MX] = true;

                    // Find the box that moved (in prev but not in curr)
                    uint16_t old_bp = 0;
                    {
                        int pi = 0, qi = 0;
                        while (pi < nb && qi < nb) {
                            if (prv.st.bx[pi] == cur2.st.bx[qi]) { pi++; qi++; }
                            else if (prv.st.bx[pi] < cur2.st.bx[qi])
                                { old_bp = prv.st.bx[pi]; break; }
                            else { qi++; }
                        }
                        if (pi < nb && qi >= nb)
                            old_bp = prv.st.bx[pi];
                    }

                    int br = old_bp / MX, bc = old_bp % MX;
                    int ppr = br - DR[d], ppc = bc - DC[d];

                    result += bfs_path(prv.pr, prv.pc, ppr, ppc,
                                       pbm, b.R, b.C, b.w);
                    result += PCH[d];
                }
                return result;
            }
        }

        // Build box map and player reachability
        bool bm[MX][MX]{};
        for (int i = 0; i < nb; i++)
            bm[cur.st.bx[i] / MX][cur.st.bx[i] % MX] = true;

        bool reach[MX][MX]{};
        {
            queue<int> rq;
            rq.push(cur.pr * MX + cur.pc);
            reach[cur.pr][cur.pc] = true;
            while (!rq.empty()) {
                int p = rq.front(); rq.pop();
                int r = p / MX, c = p % MX;
                for (int d = 0; d < 4; d++) {
                    int nr = r + DR[d], nc = c + DC[d];
                    if (!inb(nr, nc, b.R, b.C) || b.w[nr][nc] ||
                        reach[nr][nc] || bm[nr][nc])
                        continue;
                    reach[nr][nc] = true;
                    rq.push(nr * MX + nc);
                }
            }
        }

        // Try all pushes
        for (int bi = 0; bi < nb; bi++) {
            int br = cur.st.bx[bi] / MX, bc = cur.st.bx[bi] % MX;

            for (int d = 0; d < 4; d++) {
                int pnr = br - DR[d], pnc = bc - DC[d];  // player push pos
                int bdr = br + DR[d], bdc = bc + DC[d];  // box destination

                if (!inb(pnr, pnc, b.R, b.C) || !inb(bdr, bdc, b.R, b.C))
                    continue;
                if (b.w[pnr][pnc] || bm[pnr][pnc]) continue;
                if (b.w[bdr][bdc] || bm[bdr][bdc] || b.dead[bdr][bdc]) continue;
                if (!reach[pnr][pnc]) continue;

                // New state
                State ns = cur.st;
                ns.bx[bi] = (uint16_t)(bdr * MX + bdc);
                sort(ns.bx, ns.bx + nb);

                bool nbm[MX][MX]{};
                for (int i = 0; i < nb; i++)
                    nbm[ns.bx[i] / MX][ns.bx[i] % MX] = true;
                ns.pz = player_zone(br, bc, nbm, b.R, b.C, b.w);

                int ng = cur.g + 1;
                auto it = bg.find(ns);
                if (it != bg.end() && it->second <= ng) continue;
                bg[ns] = ng;

                int h = h_assign(ns, b.goal);

                OEntry ne{};
                ne.st = ns;
                ne.pr = (int16_t)br; ne.pc = (int16_t)bc;
                ne.g = ng; ne.f = ng + h;
                ne.par = ci; ne.pd = (int8_t)d;
                pq.push(ne);
            }
        }
    }

    return "";   // no solution found
}

// --------------- Main ---------------

int main(int argc, char* argv[]) {
    if (argc < 2) {
        cerr << "Usage: " << argv[0] << " <puzzle.xsb>\n";
        return 1;
    }
    Board b = parse(argv[1]);
    string sol = solve(b);
    if (sol.empty()) {
        cerr << "No solution found\n";
        return 1;
    }
    cout << sol << "\n";
    return 0;
}
