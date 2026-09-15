#include <bits/stdc++.h>
using namespace std;

static const int MAXN = 100005;
static const int MAXNODES = 4000005;

/* ---- Tree ---- */
vector<int> ch[MAXN];
int par[MAXN], dep[MAXN], sub_[MAXN], hvy[MAXN];
int hd[MAXN], hpos[MAXN], cpos;
int N, M, K;
long long iv[MAXN];

void calc_sub() {
    stack<pair<int,bool>> st;
    st.push({1, false});
    while (!st.empty()) {
        auto [u, done] = st.top(); st.pop();
        if (done) {
            sub_[u] = 1; hvy[u] = -1;
            int mx = 0;
            for (int v : ch[u]) {
                sub_[u] += sub_[v];
                if (sub_[v] > mx) { mx = sub_[v]; hvy[u] = v; }
            }
        } else {
            st.push({u, true});
            for (int v : ch[u]) { dep[v] = dep[u] + 1; st.push({v, false}); }
        }
    }
}

void calc_hld() {
    cpos = 0;
    stack<pair<int,int>> st;
    st.push({1, 1});
    while (!st.empty()) {
        auto [u, h] = st.top(); st.pop();
        hd[u] = h; hpos[u] = cpos++;
        for (int v : ch[u])
            if (v != hvy[u]) st.push({v, v});
        if (hvy[u] != -1) st.push({hvy[u], h});
    }
}

/* ---- Persistent Segment Tree ---- */
struct Node { long long s; int l, r; } T[MAXNODES];
int tc = 0;
int rt[200005];

int build(int l, int r, long long* a) {
    int nd = ++tc;
    T[nd].l = T[nd].r = 0;
    if (l == r) { T[nd].s = a[l]; return nd; }
    int m = (l + r) >> 1;
    T[nd].l = build(l, m, a);
    T[nd].r = build(m + 1, r, a);
    T[nd].s = T[T[nd].l].s + T[T[nd].r].s;
    return nd;
}

int upd(int p, int l, int r, int i, long long v) {
    int nd = ++tc;
    if (l == r) { T[nd].s = v; T[nd].l = T[nd].r = 0; return nd; }
    int m = (l + r) >> 1;
    if (i <= m) { T[nd].l = upd(T[p].l, l, m, i, v); T[nd].r = T[p].r; }
    else        { T[nd].l = T[p].l; T[nd].r = upd(T[p].r, m + 1, r, i, v); }
    T[nd].s = T[T[nd].l].s + T[T[nd].r].s;
    return nd;
}

long long qry(int nd, int l, int r, int ql, int qr) {
    if (!nd || ql > r || qr < l) return 0;
    if (ql <= l && r <= qr) return T[nd].s;
    int m = (l + r) >> 1;
    return qry(T[nd].l, l, m, ql, qr) + qry(T[nd].r, m + 1, r, ql, qr);
}

/* ---- HLD path query on a persistent version ---- */
long long path_sum(int root, int u, int v) {
    long long res = 0;
    while (hd[u] != hd[v]) {
        if (dep[hd[u]] < dep[hd[v]]) swap(u, v);
        res += qry(root, 0, N - 1, hpos[hd[u]], hpos[u]);
        u = par[hd[u]];
    }
    if (dep[u] > dep[v]) swap(u, v);
    res += qry(root, 0, N - 1, hpos[u], hpos[v]);
    return res;
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);

    cin >> N >> M >> K;
    for (int i = 2; i <= N; i++) { cin >> par[i]; ch[par[i]].push_back(i); }
    par[1] = 0;
    for (int i = 1; i <= N; i++) cin >> iv[i];

    dep[1] = 0;
    calc_sub();
    calc_hld();

    static long long mp[MAXN];
    for (int i = 1; i <= N; i++) mp[hpos[i]] = iv[i];
    rt[0] = build(0, N - 1, mp);

    for (int i = 1; i <= M; i++) {
        char op; int nd; long long val;
        cin >> op >> nd >> val;
        rt[i] = upd(rt[i - 1], 0, N - 1, hpos[nd], val);
    }

    for (int i = 0; i < K; i++) {
        char op; int v, u, w;
        cin >> op >> v >> u >> w;
        cout << path_sum(rt[v], u, w) << '\n';
    }
    return 0;
}
