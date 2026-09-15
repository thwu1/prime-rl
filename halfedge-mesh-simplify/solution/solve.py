"""
Complete QEM mesh simplification implementation.

"""

import sys
sys.path.insert(0, "/app")

import heapq
import numpy as np
from halfedge import HalfedgeMesh


def compute_face_quadric(mesh, fid):
    vids = mesh.face_vertices(fid)
    p0 = mesh.vertices[vids[0]].position
    p1 = mesh.vertices[vids[1]].position
    p2 = mesh.vertices[vids[2]].position
    normal = np.cross(p1 - p0, p2 - p0)
    length = np.linalg.norm(normal)
    if length < 1e-15:
        return np.zeros((4, 4), dtype=np.float64)
    normal = normal / length
    d = -np.dot(normal, p0)
    v = np.array([normal[0], normal[1], normal[2], d], dtype=np.float64)
    return np.outer(v, v)


def compute_vertex_quadrics(mesh):
    vq = {vid: np.zeros((4, 4), dtype=np.float64) for vid in mesh.vertices}
    for fid in mesh.faces:
        if mesh.faces[fid].boundary:
            continue
        Q = compute_face_quadric(mesh, fid)
        for vid in mesh.face_vertices(fid):
            vq[vid] = vq[vid] + Q
    return vq


def optimal_placement(Q, fallback_pos):
    A = Q[:3, :3]
    b_vec = -Q[:3, 3]
    det = np.linalg.det(A)
    if abs(det) > 1e-10:
        x = np.linalg.solve(A, b_vec)
        v_h = np.array([x[0], x[1], x[2], 1.0])
        cost = float(v_h @ Q @ v_h)
        return x, max(cost, 0.0)
    else:
        fb = np.array(fallback_pos, dtype=np.float64)
        v_h = np.array([fb[0], fb[1], fb[2], 1.0])
        cost = float(v_h @ Q @ v_h)
        return fb.copy(), max(cost, 0.0)


def check_collapse_valid(mesh, eid):
    if mesh.is_boundary_edge(eid):
        return False
    v0, v1 = mesh.edge_vertices(eid)
    n0 = set(mesh.vertex_vertices(v0))
    n1 = set(mesh.vertex_vertices(v1))
    common = (n0 - {v1}) & (n1 - {v0})
    if len(common) != 2:
        return False
    merged = (n0 | n1) - {v0, v1}
    if len(merged) < 3:
        return False
    return True


def collapse_edge(mesh, eid, new_pos):
    h0_id = mesh.edges[eid].halfedge
    h0 = mesh.halfedges[h0_id]
    h1_id = h0.twin
    h1 = mesh.halfedges[h1_id]

    v0 = h0.vertex   # survives
    v1 = h1.vertex    # removed

    f0 = h0.face
    f1 = h1.face

    mesh.vertices[v0].position = np.array(new_pos, dtype=np.float64)

    # ---- face f0: h0(v0->v1), b(v1->w0), c(w0->v0) ----
    b_id = h0.next
    b = mesh.halfedges[b_id]
    c_id = b.next
    c = mesh.halfedges[c_id]
    w0 = c.vertex

    bt_id = b.twin
    ct_id = c.twin

    mesh.halfedges[bt_id].twin = ct_id
    mesh.halfedges[ct_id].twin = bt_id

    surviving_edge_0 = c.edge
    dead_edge_0 = b.edge
    mesh.halfedges[bt_id].edge = surviving_edge_0
    mesh.edges[surviving_edge_0].halfedge = bt_id

    if mesh.vertices[w0].halfedge in (c_id, b_id, h0_id):
        mesh.vertices[w0].halfedge = bt_id

    mesh.remove_halfedge(h0_id)
    mesh.remove_halfedge(b_id)
    mesh.remove_halfedge(c_id)
    mesh.remove_edge(dead_edge_0)
    mesh.remove_face(f0)

    # ---- face f1: h1(v1->v0), d(v0->w1), e(w1->v1) ----
    d_id = h1.next
    d = mesh.halfedges[d_id]
    e_id = d.next
    e = mesh.halfedges[e_id]
    w1 = e.vertex

    dt_id = d.twin
    et_id = e.twin

    mesh.halfedges[dt_id].twin = et_id
    mesh.halfedges[et_id].twin = dt_id

    surviving_edge_1 = e.edge
    dead_edge_1 = d.edge
    mesh.halfedges[dt_id].edge = surviving_edge_1
    mesh.edges[surviving_edge_1].halfedge = dt_id

    if mesh.vertices[w1].halfedge in (e_id, d_id, h1_id):
        mesh.vertices[w1].halfedge = dt_id

    mesh.remove_halfedge(h1_id)
    mesh.remove_halfedge(d_id)
    mesh.remove_halfedge(e_id)
    mesh.remove_edge(dead_edge_1)
    mesh.remove_face(f1)

    # ---- redirect all remaining halfedges from v1 to v0 ----
    for hid in list(mesh.halfedges.keys()):
        if mesh.halfedges[hid].vertex == v1:
            mesh.halfedges[hid].vertex = v0

    # ---- fix v0.halfedge ----
    for hid in mesh.halfedges:
        if mesh.halfedges[hid].vertex == v0:
            mesh.vertices[v0].halfedge = hid
            break

    # ---- remove collapsed edge and dead vertex ----
    mesh.remove_edge(eid)
    mesh.remove_vertex(v1)

    return v0


def simplify(mesh, target_face_count):
    vq = compute_vertex_quadrics(mesh)

    heap = []
    counter = 0
    edge_gen = {}   # eid -> generation counter of current valid entry

    def enqueue_edge(eid):
        nonlocal counter
        if eid not in mesh.edges:
            return
        if mesh.is_boundary_edge(eid):
            return
        va, vb = mesh.edge_vertices(eid)
        Q = vq.get(va, np.zeros((4, 4))) + vq.get(vb, np.zeros((4, 4)))
        mid = (mesh.vertices[va].position + mesh.vertices[vb].position) / 2.0
        pos, cost = optimal_placement(Q, mid)
        gen = counter
        counter += 1
        edge_gen[eid] = gen
        heapq.heappush(heap, (cost, gen, eid, pos))

    for eid in list(mesh.edges.keys()):
        enqueue_edge(eid)

    while mesh.n_faces() > target_face_count and heap:
        cost, gen, eid, pos = heapq.heappop(heap)

        if eid not in mesh.edges:
            continue
        if edge_gen.get(eid) != gen:
            continue

        if not check_collapse_valid(mesh, eid):
            del edge_gen[eid]
            continue

        va, vb = mesh.edge_vertices(eid)
        Q_new = vq.get(va, np.zeros((4, 4))) + vq.get(vb, np.zeros((4, 4)))

        new_vid = collapse_edge(mesh, eid, pos)

        vq[new_vid] = Q_new
        if vb != new_vid and vb in vq:
            del vq[vb]
        if va != new_vid and va in vq:
            del vq[va]

        if eid in edge_gen:
            del edge_gen[eid]

        for e in mesh.vertex_edges(new_vid):
            enqueue_edge(e)


def main():
    """Write the implementation to /app/simplify.py."""
    import inspect
    source_lines = []

    source_lines.append('"""')
    source_lines.append("Quadric Error Metrics mesh simplification.")
    source_lines.append("")
    source_lines.append('"""')
    source_lines.append("")
    source_lines.append("import heapq")
    source_lines.append("import numpy as np")
    source_lines.append("from halfedge import HalfedgeMesh")
    source_lines.append("")

    for func in [compute_face_quadric, compute_vertex_quadrics,
                 optimal_placement, check_collapse_valid,
                 collapse_edge, simplify]:
        src = inspect.getsource(func)
        source_lines.append(src)
        source_lines.append("")

    with open("/app/simplify.py", "w") as f:
        f.write("\n".join(source_lines))

    print("Wrote /app/simplify.py")


if __name__ == "__main__":
    main()
