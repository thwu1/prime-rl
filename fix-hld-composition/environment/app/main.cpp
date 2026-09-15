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
//
// You must implement: build, update, query_fwd, query_rev.
// ============================================================

struct SegTree {
    int n;
    vector<Affine> fwd, rev;

    SegTree() : n(0) {}
    SegTree(int n_) : n(n_), fwd(4 * n_ + 4), rev(4 * n_ + 4) {}

    // Build from vector v of size n (indexed 0..n-1).
    void build(const vector<Affine>& v) {
        // TODO: implement recursive build
        // After building, each leaf should store v[i] in both fwd and rev.
        // Each internal node should combine its children's compositions.
    }

    // Point update: set the function at position p.
    void update(int p, const Affine& val) {
        // TODO: implement
    }

    // Forward query [ql, qr]: compose applying ql first, qr last.
    // Returns f_qr . f_{qr-1} . ... . f_ql
    Affine query_fwd(int ql, int qr) {
        // TODO: implement
        return Affine(); // stub: returns identity
    }

    // Reverse query [ql, qr]: compose applying qr first, ql last.
    // Returns f_ql . f_{ql+1} . ... . f_qr
    Affine query_rev(int ql, int qr) {
        // TODO: implement
        return Affine(); // stub: returns identity
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
// The HLD assigns each node an euler_pos such that each heavy chain
// occupies a contiguous range. Ancestors have smaller positions than
// descendants within the same chain. Use this to decompose the path
// into O(log n) segments and compose them in the correct direction.
// ============================================================

Affine query_path(int u, int v, Tree& tree, SegTree& seg) {
    // TODO: implement
    // Decompose the u-to-v path through the LCA.
    // The u-to-LCA side traverses upward (deep to shallow).
    // The LCA-to-v side traverses downward (shallow to deep).
    // Choose the correct query direction (fwd vs rev) for each side.
    return Affine(); // stub: returns identity
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
