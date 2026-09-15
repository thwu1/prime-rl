#include <bits/stdc++.h>
using namespace std;


const long long MOD = 998244353;

long long mod_val(long long x) {
    return ((x % MOD) + MOD) % MOD;
}

long long power(long long base, long long exp, long long mod) {
    long long result = 1;
    base %= mod;
    if (base < 0) base += mod;
    while (exp > 0) {
        if (exp & 1) result = result * base % mod;
        base = base * base % mod;
        exp >>= 1;
    }
    return result;
}

// Affine function f(x) = a*x + b (mod MOD)
struct Affine {
    long long a, b;
    Affine() : a(1), b(0) {} // identity: f(x) = x
    Affine(long long a_, long long b_) : a(mod_val(a_)), b(mod_val(b_)) {}

    long long eval(long long x) const {
        return mod_val(mod_val(a * mod_val(x)) + b);
    }

    // Compose: this(other(x)) = a*(other.a*x + other.b) + b
    // "first apply other, then apply this"
    Affine compose(const Affine& other) const {
        return Affine(
            mod_val(a * other.a),
            mod_val(mod_val(a * other.b) + b)
        );
    }
};

// ============================================================
// Segment tree for non-commutative affine function composition.
//
// Each internal node covers a range [l, r] of positions and stores:
//   fwd: the composition applying position l first, then l+1, ..., then r
//        i.e. f_r(f_{r-1}(...(f_l(x))...))  =  f_r . f_{r-1} . ... . f_l
//   rev: the composition applying position r first, then r-1, ..., then l
//        i.e. f_l(f_{l+1}(...(f_r(x))...))  =  f_l . f_{l+1} . ... . f_r
// ============================================================

struct SegTree {
    int n;
    vector<Affine> fwd, rev;

    SegTree() : n(0) {}
    SegTree(int n_) : n(n_), fwd(4 * n_ + 4), rev(4 * n_ + 4) {}

    void build_impl(int x, int l, int r, const vector<Affine>& v) {
        if (l == r) {
            fwd[x] = rev[x] = v[l];
            return;
        }
        int mid = (l + r) / 2;
        build_impl(2 * x, l, mid, v);
        build_impl(2 * x + 1, mid + 1, r, v);
        // fwd: apply left first, then right => right.compose(left)
        fwd[x] = fwd[2 * x + 1].compose(fwd[2 * x]);
        // rev: apply right first, then left => left.compose(right)
        rev[x] = rev[2 * x].compose(rev[2 * x + 1]);
    }

    void build(const vector<Affine>& v) {
        if (n > 0) build_impl(1, 0, n - 1, v);
    }

    void update_impl(int x, int l, int r, int p, const Affine& val) {
        if (l == r) {
            fwd[x] = rev[x] = val;
            return;
        }
        int mid = (l + r) / 2;
        if (p <= mid) update_impl(2 * x, l, mid, p, val);
        else update_impl(2 * x + 1, mid + 1, r, p, val);
        fwd[x] = fwd[2 * x + 1].compose(fwd[2 * x]);
        rev[x] = rev[2 * x].compose(rev[2 * x + 1]);
    }

    void update(int p, const Affine& val) {
        update_impl(1, 0, n - 1, p, val);
    }

    // Forward query [ql, qr]: compose applying ql first, qr last.
    // Returns f_qr . f_{qr-1} . ... . f_ql
    Affine qfwd_impl(int x, int l, int r, int ql, int qr) {
        if (ql <= l && r <= qr) return fwd[x];
        int mid = (l + r) / 2;
        if (qr <= mid) return qfwd_impl(2 * x, l, mid, ql, qr);
        if (ql > mid) return qfwd_impl(2 * x + 1, mid + 1, r, ql, qr);
        Affine lf = qfwd_impl(2 * x, l, mid, ql, mid);
        Affine rt = qfwd_impl(2 * x + 1, mid + 1, r, mid + 1, qr);
        return rt.compose(lf);
    }

    Affine query_fwd(int ql, int qr) {
        if (ql > qr) return Affine();
        return qfwd_impl(1, 0, n - 1, ql, qr);
    }

    // Reverse query [ql, qr]: compose applying qr first, ql last.
    // Returns f_ql . f_{ql+1} . ... . f_qr
    Affine qrev_impl(int x, int l, int r, int ql, int qr) {
        if (ql <= l && r <= qr) return rev[x];
        int mid = (l + r) / 2;
        if (qr <= mid) return qrev_impl(2 * x, l, mid, ql, qr);
        if (ql > mid) return qrev_impl(2 * x + 1, mid + 1, r, ql, qr);
        Affine lf = qrev_impl(2 * x, l, mid, ql, mid);
        Affine rt = qrev_impl(2 * x + 1, mid + 1, r, mid + 1, qr);
        return lf.compose(rt);
    }

    Affine query_rev(int ql, int qr) {
        if (ql > qr) return Affine();
        return qrev_impl(1, 0, n - 1, ql, qr);
    }
};

// ============================================================
// Tree with Heavy-Light Decomposition
// ============================================================

struct Tree {
    int n;
    vector<vector<int>> adj;
    vector<int> par, dep, sz, heavy, head_node, euler_pos;
    int timer;

    Tree(int n_) : n(n_), adj(n_), par(n_), dep(n_), sz(n_),
                   heavy(n_, -1), head_node(n_), euler_pos(n_), timer(0) {}

    void add_edge(int u, int v) {
        adj[u].push_back(v);
        adj[v].push_back(u);
    }

    void dfs(int v, int p, int d) {
        par[v] = p;
        dep[v] = d;
        sz[v] = 1;
        int best = 0;
        for (int u : adj[v]) {
            if (u == p) continue;
            dfs(u, v, d + 1);
            sz[v] += sz[u];
            if (sz[u] > best) {
                best = sz[u];
                heavy[v] = u;
            }
        }
    }

    void decompose(int v, int h) {
        head_node[v] = h;
        euler_pos[v] = timer++;
        if (heavy[v] != -1) {
            decompose(heavy[v], h);
        }
        for (int u : adj[v]) {
            if (u == par[v] || u == heavy[v]) continue;
            decompose(u, u);
        }
    }

    void build(int root = 0) {
        timer = 0;
        dfs(root, -1, 0);
        decompose(root, root);
    }

    int lca(int u, int v) {
        while (head_node[u] != head_node[v]) {
            if (dep[head_node[u]] < dep[head_node[v]]) swap(u, v);
            u = par[head_node[u]];
        }
        return dep[u] < dep[v] ? u : v;
    }
};

// ============================================================
// Path query: compose affine functions along the unique path u -> v.
// The result should apply f_u first, then each node toward v, ending at f_v.
//
// HLD assigns each node an euler_pos such that each heavy chain
// occupies a contiguous range. Ancestors have smaller positions than
// descendants within the same chain.
// ============================================================

Affine query_path(int u, int v, Tree& tree, SegTree& seg) {
    int z = tree.lca(u, v);

    // u-side: compose from u upward to LCA (excluding LCA)
    // Walking upward (deep to shallow) => apply deeper positions first => query_rev
    Affine result_u; // identity
    int cu = u;
    while (tree.head_node[cu] != tree.head_node[z]) {
        Affine seg_r = seg.query_rev(
            tree.euler_pos[tree.head_node[cu]], tree.euler_pos[cu]);
        result_u = seg_r.compose(result_u);
        cu = tree.par[tree.head_node[cu]];
    }
    if (cu != z) {
        Affine seg_r = seg.query_rev(
            tree.euler_pos[z] + 1, tree.euler_pos[cu]);
        result_u = seg_r.compose(result_u);
    }

    // LCA node
    Affine lca_fn = seg.query_fwd(tree.euler_pos[z], tree.euler_pos[z]);

    // v-side: compose from LCA+1 downward to v
    // Collect segments from v upward, then process in reverse order
    // Walking downward (shallow to deep) => apply shallower positions first => query_fwd
    vector<pair<int,int>> v_segs;
    int cv = v;
    while (tree.head_node[cv] != tree.head_node[z]) {
        v_segs.push_back({tree.euler_pos[tree.head_node[cv]],
                          tree.euler_pos[cv]});
        cv = tree.par[tree.head_node[cv]];
    }
    if (cv != z) {
        v_segs.push_back({tree.euler_pos[z] + 1, tree.euler_pos[cv]});
    }

    Affine result_v; // identity
    for (int i = (int)v_segs.size() - 1; i >= 0; i--) {
        Affine seg_r = seg.query_fwd(v_segs[i].first, v_segs[i].second);
        result_v = seg_r.compose(result_v);
    }

    // Combine: first apply result_u (u toward LCA), then lca_fn, then result_v (LCA toward v)
    return result_v.compose(lca_fn.compose(result_u));
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);

    int n, q;
    cin >> n >> q;

    Tree tree(n);
    for (int i = 0; i < n - 1; i++) {
        int u, v;
        cin >> u >> v;
        u--; v--;
        tree.add_edge(u, v);
    }
    tree.build(0);

    // Read initial functions, placing them at their HLD euler tour positions
    vector<Affine> init(n);
    for (int i = 0; i < n; i++) {
        long long a, b;
        cin >> a >> b;
        init[tree.euler_pos[i]] = Affine(a, b);
    }

    SegTree seg(n);
    seg.build(init);

    while (q--) {
        int type;
        cin >> type;
        if (type == 1) {
            int v;
            long long a, b;
            cin >> v >> a >> b;
            v--;
            seg.update(tree.euler_pos[v], Affine(a, b));
        } else if (type == 2) {
            int u, v;
            long long x;
            cin >> u >> v >> x;
            u--; v--;
            Affine f = query_path(u, v, tree, seg);
            cout << f.eval(x) << "\n";
        } else {
            // Type 3: find x such that path_compose(u,v)(x) = y (mod MOD)
            int u, v;
            long long y;
            cin >> u >> v >> y;
            u--; v--;
            Affine f = query_path(u, v, tree, seg);
            if (f.a == 0) {
                if (f.b == mod_val(y))
                    cout << 0 << "\n";
                else
                    cout << -1 << "\n";
            } else {
                long long inv_a = power(f.a, MOD - 2, MOD);
                cout << mod_val(inv_a * mod_val(y - f.b)) << "\n";
            }
        }
    }
    return 0;
}
