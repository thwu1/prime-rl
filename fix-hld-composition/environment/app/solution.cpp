#include <bits/stdc++.h>
using namespace std;


const long long MOD = 998244353;

long long mod_val(long long x) {
    return ((x % MOD) + MOD) % MOD;
}

// Affine function f(x) = a*x + b (mod MOD)
struct Affine {
    long long a, b;
    Affine() : a(1), b(0) {} // identity
    Affine(long long a_, long long b_) : a(mod_val(a_)), b(mod_val(b_)) {}

    long long eval(long long x) const {
        return mod_val(mod_val(a * mod_val(x)) + b);
    }

    // Returns composition: first apply `other`, then apply `this`
    // this(other(x)) = a * (other.a * x + other.b) + b
    //                = (a * other.a) * x + (a * other.b + b)
    Affine after(const Affine& other) const {
        return Affine(
            mod_val(a * other.a),
            mod_val(mod_val(a * other.b) + other.b)
        );
    }
};

// Segment tree node: stores forward and reverse compositions
struct Node {
    Affine fwd; // composition applying left positions first
    Affine rev; // composition applying right positions first
};

struct SegTree {
    int n;
    vector<Node> tree;

    SegTree() : n(0) {}
    SegTree(int n_) : n(n_), tree(4 * n_ + 4) {}

    Node unite(const Node& left, const Node& right) {
        Node res;
        res.fwd = right.fwd.after(left.fwd);
        res.rev = left.rev.after(right.rev);
        return res;
    }

    void build(int x, int l, int r, const vector<Affine>& v) {
        if (l == r) {
            tree[x].fwd = tree[x].rev = v[l];
            return;
        }
        int mid = (l + r) / 2;
        build(2 * x, l, mid, v);
        build(2 * x + 1, mid + 1, r, v);
        tree[x] = unite(tree[2 * x], tree[2 * x + 1]);
    }

    void build(const vector<Affine>& v) {
        if (n > 0) build(1, 0, n - 1, v);
    }

    void update(int x, int l, int r, int p, const Affine& val) {
        if (l == r) {
            tree[x].fwd = tree[x].rev = val;
            return;
        }
        int mid = (l + r) / 2;
        if (p <= mid) update(2 * x, l, mid, p, val);
        else update(2 * x + 1, mid + 1, r, p, val);
        tree[x] = unite(tree[2 * x], tree[2 * x + 1]);
    }

    void update(int p, const Affine& val) {
        update(1, 0, n - 1, p, val);
    }

    // Forward query: compose applying left positions first
    Affine query_fwd(int x, int l, int r, int ql, int qr) {
        if (ql > qr) return Affine();
        if (ql <= l && r <= qr) return tree[x].fwd;
        int mid = (l + r) / 2;
        if (qr <= mid) return query_fwd(2 * x, l, mid, ql, qr);
        if (ql > mid) return query_fwd(2 * x + 1, mid + 1, r, ql, qr);
        Affine lf = query_fwd(2 * x, l, mid, ql, mid);
        Affine rt = query_fwd(2 * x + 1, mid + 1, r, mid + 1, qr);
        return rt.after(lf);
    }

    Affine query_fwd(int ql, int qr) {
        if (ql > qr) return Affine();
        return query_fwd(1, 0, n - 1, ql, qr);
    }

    // Reverse query: compose applying right positions first
    Affine query_rev(int x, int l, int r, int ql, int qr) {
        if (ql > qr) return Affine();
        if (ql <= l && r <= qr) return tree[x].rev;
        int mid = (l + r) / 2;
        if (qr <= mid) return query_rev(2 * x, l, mid, ql, qr);
        if (ql > mid) return query_rev(2 * x + 1, mid + 1, r, ql, qr);
        Affine lf = query_rev(2 * x, l, mid, ql, mid);
        Affine rt = query_rev(2 * x + 1, mid + 1, r, mid + 1, qr);
        return lf.after(rt);
    }

    Affine query_rev(int ql, int qr) {
        if (ql > qr) return Affine();
        return query_rev(1, 0, n - 1, ql, qr);
    }
};

struct Tree {
    int n;
    vector<vector<int>> adj;
    vector<int> par, dep, sub_sz, heavy, head_node, euler_pos;
    int timer;

    Tree(int n_) : n(n_), adj(n_), par(n_), dep(n_), sub_sz(n_),
                   heavy(n_, -1), head_node(n_), euler_pos(n_), timer(0) {}

    void add_edge(int u, int v) {
        adj[u].push_back(v);
        adj[v].push_back(u);
    }

    void dfs(int v, int p, int d) {
        par[v] = p;
        dep[v] = d;
        sub_sz[v] = 1;
        int best = 0;
        for (int u : adj[v]) {
            if (u == p) continue;
            dfs(u, v, d + 1);
            sub_sz[v] += sub_sz[u];
            if (sub_sz[u] > best) {
                best = sub_sz[u];
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

    // Compose affine functions along path from u to v
    // Apply f_u first, then next node toward v, ..., finally f_v
    Affine query_path(int u, int v, SegTree& seg) {
        int z = lca(u, v);

        // u-side: compose from u upward to z (excluding z)
        // Traversal goes from deeper node toward root
        Affine result_u; // identity
        int cu = u;
        while (head_node[cu] != head_node[z]) {
            Affine seg_result = seg.query_fwd(euler_pos[head_node[cu]], euler_pos[cu]);
            result_u = seg_result.after(result_u);
            cu = par[head_node[cu]];
        }
        // Remaining segment on same chain as z
        if (cu != z) {
            Affine seg_result = seg.query_fwd(euler_pos[z], euler_pos[cu]);
            result_u = seg_result.after(result_u);
        }

        // LCA node
        Affine lca_fn = seg.query_fwd(euler_pos[z], euler_pos[z]);

        // v-side: compose from z downward to v (excluding z)
        // Collect segments from v upward, then process in reverse order
        vector<pair<int,int>> v_segs;
        int cv = v;
        while (head_node[cv] != head_node[z]) {
            v_segs.push_back({euler_pos[head_node[cv]], euler_pos[cv]});
            cv = par[head_node[cv]];
        }
        if (cv != z) {
            v_segs.push_back({euler_pos[z] + 1, euler_pos[cv]});
        }

        // Process segments from z toward v (reverse of collection order)
        Affine result_v; // identity
        for (int i = (int)v_segs.size() - 1; i >= 0; i--) {
            Affine seg_result = seg.query_fwd(v_segs[i].first, v_segs[i].second);
            result_v = seg_result.after(result_v);
        }

        // Combine: u-side, then LCA, then v-side
        return result_v.after(lca_fn.after(result_u));
    }
};

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

    vector<Affine> init(n);
    for (int i = 0; i < n; i++) {
        long long a, b;
        cin >> a >> b;
        init[i] = Affine(a, b);
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
        } else {
            int u, v;
            long long x;
            cin >> u >> v >> x;
            u--; v--;
            Affine result = tree.query_path(u, v, seg);
            cout << result.eval(x) << "\n";
        }
    }

    return 0;
}
