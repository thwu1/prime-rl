
"""
Implement the segment tree and path query in /app/main.cpp.

The segment tree needs:
- Recursive build maintaining both forward and reverse compositions
- Point update maintaining both compositions
- Forward query: compose left-to-right (position l applied first)
- Reverse query: compose right-to-left (position r applied first)

The path query needs:
- Decompose u->v path through LCA using HLD
- u-side (upward): use reverse queries (deep positions applied first)
- v-side (downward): collect segments from v upward, reverse, use forward queries
- Combine: result_v.compose(lca_fn.compose(result_u))
"""

import os
import sys

source_path = "/app/main.cpp"

if not os.path.exists(source_path):
    backup_path = "/opt/initial_app/main.cpp"
    if os.path.exists(backup_path):
        import shutil
        shutil.copy2(backup_path, source_path)
    else:
        print(f"ERROR: Cannot find main.cpp", file=sys.stderr)
        sys.exit(1)

with open(source_path, "r") as f:
    code = f.read()

# Replace the stub SegTree::build with full implementation
code = code.replace(
    """    // Build from vector v of size n (indexed 0..n-1).
    void build(const vector<Affine>& v) {
        // TODO: implement recursive build
        // After building, each leaf should store v[i] in both fwd and rev.
        // Each internal node should combine its children's compositions.
    }""",
    """    void build_impl(int x, int l, int r, const vector<Affine>& v) {
        if (l == r) {
            fwd[x] = rev[x] = v[l];
            return;
        }
        int mid = (l + r) / 2;
        build_impl(2 * x, l, mid, v);
        build_impl(2 * x + 1, mid + 1, r, v);
        fwd[x] = fwd[2 * x + 1].compose(fwd[2 * x]);
        rev[x] = rev[2 * x].compose(rev[2 * x + 1]);
    }

    void build(const vector<Affine>& v) {
        if (n > 0) build_impl(1, 0, n - 1, v);
    }""",
)

# Replace the stub SegTree::update with full implementation
code = code.replace(
    """    // Point update: set the function at position p.
    void update(int p, const Affine& val) {
        // TODO: implement
    }""",
    """    void update_impl(int x, int l, int r, int p, const Affine& val) {
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
    }""",
)

# Replace the stub query_fwd with full implementation
code = code.replace(
    """    // Forward query [ql, qr]: compose applying ql first, qr last.
    // Returns f_qr . f_{qr-1} . ... . f_ql
    Affine query_fwd(int ql, int qr) {
        // TODO: implement
        return Affine(); // stub: returns identity
    }""",
    """    Affine qfwd_impl(int x, int l, int r, int ql, int qr) {
        if (ql > qr) return Affine();
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
    }""",
)

# Replace the stub query_rev with full implementation
code = code.replace(
    """    // Reverse query [ql, qr]: compose applying qr first, ql last.
    // Returns f_ql . f_{ql+1} . ... . f_qr
    Affine query_rev(int ql, int qr) {
        // TODO: implement
        return Affine(); // stub: returns identity
    }""",
    """    Affine qrev_impl(int x, int l, int r, int ql, int qr) {
        if (ql > qr) return Affine();
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
    }""",
)

# Replace the stub query_path with full implementation
code = code.replace(
    """Affine query_path(int u, int v, Tree& tree, SegTree& seg) {
    // TODO: implement
    // Decompose the u-to-v path through the LCA.
    // The u-to-LCA side traverses upward (deep to shallow).
    // The LCA-to-v side traverses downward (shallow to deep).
    // Choose the correct query direction (fwd vs rev) for each side.
    return Affine(); // stub: returns identity
}""",
    """Affine query_path(int u, int v, Tree& tree, SegTree& seg) {
    int z = tree.lca(u, v);

    // u-side: compose from u upward to LCA (excluding LCA)
    // Walking upward means applying deeper positions first -> use query_rev
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
    // Walking downward means applying shallower positions first -> use query_fwd
    vector<pair<int, int>> v_segs;
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

    // Combine: first apply result_u (u toward LCA), then lca_fn, then result_v
    return result_v.compose(lca_fn.compose(result_u));
}""",
)

with open(source_path, "w") as f:
    f.write(code)

print("Implementation complete: segment tree and path query filled in")
