"""
Halfedge mesh data structure for manifold triangle meshes.

Provides construction from indexed face lists, topological traversal,
low-level element modification, export, and validation.

"""

import numpy as np


class Vertex:
    __slots__ = ['id', 'position', 'halfedge']

    def __init__(self, vid, position):
        self.id = vid
        self.position = np.array(position, dtype=np.float64)
        self.halfedge = None  # ID of one outgoing halfedge


class Edge:
    __slots__ = ['id', 'halfedge']

    def __init__(self, eid):
        self.id = eid
        self.halfedge = None  # ID of one constituent halfedge


class Face:
    __slots__ = ['id', 'halfedge', 'boundary']

    def __init__(self, fid, boundary=False):
        self.id = fid
        self.halfedge = None  # ID of one halfedge in the face loop
        self.boundary = boundary


class Halfedge:
    __slots__ = ['id', 'twin', 'next', 'vertex', 'edge', 'face']

    def __init__(self, hid):
        self.id = hid
        self.twin = None    # ID of opposite halfedge on same edge
        self.next = None    # ID of next halfedge in face loop
        self.vertex = None  # ID of source vertex
        self.edge = None    # ID of parent edge
        self.face = None    # ID of incident face


class HalfedgeMesh:
    """Pointer-based halfedge mesh.

    All elements are stored in ``dict``s keyed by integer IDs.
    Connectivity is expressed through ID cross-references.
    """

    def __init__(self):
        self.vertices = {}
        self.edges = {}
        self.faces = {}
        self.halfedges = {}
        self._next_id = 0

    def _alloc_id(self):
        i = self._next_id
        self._next_id += 1
        return i

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_indexed_faces(cls, positions, faces):
        """Build a halfedge mesh from positions and 0-based face-index lists."""
        mesh = cls()

        vid_list = []
        for p in positions:
            vid = mesh._alloc_id()
            mesh.vertices[vid] = Vertex(vid, p)
            vid_list.append(vid)

        oriented_he = {}

        for face_idx in faces:
            fid = mesh._alloc_id()
            face = Face(fid)
            mesh.faces[fid] = face

            n = len(face_idx)
            he_ids = []
            for i in range(n):
                v_from = vid_list[face_idx[i]]
                v_to = vid_list[face_idx[(i + 1) % n]]
                hid = mesh._alloc_id()
                he = Halfedge(hid)
                he.vertex = v_from
                he.face = fid
                mesh.halfedges[hid] = he
                he_ids.append(hid)
                oriented_he[(v_from, v_to)] = hid

            for i in range(n):
                mesh.halfedges[he_ids[i]].next = he_ids[(i + 1) % n]
            face.halfedge = he_ids[0]

        created_edges = {}
        for (v0, v1), hid in oriented_he.items():
            ekey = (min(v0, v1), max(v0, v1))
            if ekey not in created_edges:
                eid = mesh._alloc_id()
                edge = Edge(eid)
                edge.halfedge = hid
                mesh.edges[eid] = edge
                created_edges[ekey] = eid
            mesh.halfedges[hid].edge = created_edges[ekey]

            twin_key = (v1, v0)
            if twin_key in oriented_he:
                tid = oriented_he[twin_key]
                mesh.halfedges[hid].twin = tid
                mesh.halfedges[tid].twin = hid

        for hid, he in mesh.halfedges.items():
            vid = he.vertex
            if mesh.vertices[vid].halfedge is None:
                mesh.vertices[vid].halfedge = hid

        return mesh

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    def n_vertices(self):
        return len(self.vertices)

    def n_edges(self):
        return len(self.edges)

    def n_faces(self):
        return sum(1 for f in self.faces.values() if not f.boundary)

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def face_vertices(self, fid):
        """Ordered vertex IDs around a face."""
        result = []
        start = self.faces[fid].halfedge
        h = start
        for _ in range(len(self.halfedges) + 1):
            result.append(self.halfedges[h].vertex)
            h = self.halfedges[h].next
            if h == start:
                break
        return result

    def face_edges(self, fid):
        """Edge IDs around a face."""
        result = []
        start = self.faces[fid].halfedge
        h = start
        for _ in range(len(self.halfedges) + 1):
            result.append(self.halfedges[h].edge)
            h = self.halfedges[h].next
            if h == start:
                break
        return result

    def face_halfedges(self, fid):
        """Halfedge IDs around a face."""
        result = []
        start = self.faces[fid].halfedge
        h = start
        for _ in range(len(self.halfedges) + 1):
            result.append(h)
            h = self.halfedges[h].next
            if h == start:
                break
        return result

    def vertex_halfedges(self, vid):
        """Outgoing halfedge IDs from a vertex (one-ring traversal via twin->next)."""
        result = []
        start = self.vertices[vid].halfedge
        if start is None:
            return result
        h = start
        for _ in range(len(self.halfedges) + 1):
            result.append(h)
            twin = self.halfedges[h].twin
            if twin is None:
                break
            h = self.halfedges[twin].next
            if h == start:
                break
        return result

    def vertex_vertices(self, vid):
        """Adjacent vertex IDs (tip of each outgoing halfedge's twin)."""
        result = []
        for hid in self.vertex_halfedges(vid):
            twin = self.halfedges[hid].twin
            if twin is not None:
                result.append(self.halfedges[twin].vertex)
        return result

    def vertex_faces(self, vid):
        """Non-boundary face IDs incident to a vertex."""
        result = []
        for hid in self.vertex_halfedges(vid):
            fid = self.halfedges[hid].face
            if fid is not None and not self.faces[fid].boundary:
                result.append(fid)
        return result

    def vertex_edges(self, vid):
        """Edge IDs incident to a vertex."""
        seen = set()
        result = []
        for hid in self.vertex_halfedges(vid):
            eid = self.halfedges[hid].edge
            if eid is not None and eid not in seen:
                seen.add(eid)
                result.append(eid)
        return result

    def edge_vertices(self, eid):
        """Return (v0, v1) vertex IDs of an edge."""
        hid = self.edges[eid].halfedge
        he = self.halfedges[hid]
        return he.vertex, self.halfedges[he.twin].vertex

    def edge_faces(self, eid):
        """Return (f0, f1) face IDs adjacent to an edge."""
        hid = self.edges[eid].halfedge
        he = self.halfedges[hid]
        f0 = he.face
        f1 = self.halfedges[he.twin].face if he.twin is not None else None
        return f0, f1

    def is_boundary_edge(self, eid):
        """True if either adjacent face is a boundary face or twin is missing."""
        hid = self.edges[eid].halfedge
        he = self.halfedges[hid]
        if he.twin is None:
            return True
        f0 = he.face
        f1 = self.halfedges[he.twin].face
        if f0 is not None and self.faces[f0].boundary:
            return True
        if f1 is not None and self.faces[f1].boundary:
            return True
        return False

    # ------------------------------------------------------------------
    # Element removal (low-level, does NOT fix dangling references)
    # ------------------------------------------------------------------

    def remove_vertex(self, vid):
        del self.vertices[vid]

    def remove_edge(self, eid):
        del self.edges[eid]

    def remove_face(self, fid):
        del self.faces[fid]

    def remove_halfedge(self, hid):
        del self.halfedges[hid]

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_indexed_faces(self):
        """Return (positions, faces) with 0-based indices, skipping boundary faces."""
        vid_to_idx = {}
        positions = []
        for i, vid in enumerate(sorted(self.vertices.keys())):
            vid_to_idx[vid] = i
            positions.append(list(self.vertices[vid].position))

        faces = []
        for fid in sorted(self.faces.keys()):
            if self.faces[fid].boundary:
                continue
            vids = self.face_vertices(fid)
            faces.append([vid_to_idx[v] for v in vids])

        return positions, faces

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self):
        """Return a list of error strings.  Empty list means the mesh is valid."""
        errors = []

        # -- reference integrity --
        for hid, he in self.halfedges.items():
            if he.vertex not in self.vertices:
                errors.append(f"HE {hid}: vertex {he.vertex} missing")
            if he.edge not in self.edges:
                errors.append(f"HE {hid}: edge {he.edge} missing")
            if he.face not in self.faces:
                errors.append(f"HE {hid}: face {he.face} missing")
            if he.next not in self.halfedges:
                errors.append(f"HE {hid}: next {he.next} missing")
            if he.twin is not None and he.twin not in self.halfedges:
                errors.append(f"HE {hid}: twin {he.twin} missing")
        if errors:
            return errors

        # -- twin symmetry --
        for hid, he in self.halfedges.items():
            if he.twin is not None:
                if self.halfedges[he.twin].twin != hid:
                    errors.append(
                        f"HE {hid}: twin's twin is "
                        f"{self.halfedges[he.twin].twin}, expected {hid}")

        # -- edge-halfedge consistency --
        for eid, edge in self.edges.items():
            hid = edge.halfedge
            if hid not in self.halfedges:
                errors.append(f"Edge {eid}: halfedge {hid} missing")
                continue
            he = self.halfedges[hid]
            if he.edge != eid:
                errors.append(f"Edge {eid}: he {hid} -> edge {he.edge}")
            if he.twin is not None:
                if self.halfedges[he.twin].edge != eid:
                    errors.append(
                        f"Edge {eid}: twin he {he.twin} -> edge "
                        f"{self.halfedges[he.twin].edge}")

        # -- face cycles --
        he_by_face = {}
        for hid, he in self.halfedges.items():
            he_by_face.setdefault(he.face, set()).add(hid)

        for fid, face in self.faces.items():
            hid = face.halfedge
            if hid not in self.halfedges:
                errors.append(f"Face {fid}: halfedge {hid} missing")
                continue

            reachable = set()
            h = hid
            for _ in range(len(self.halfedges) + 1):
                reachable.add(h)
                if self.halfedges[h].face != fid:
                    errors.append(f"Face {fid}: he {h} -> face {self.halfedges[h].face}")
                h = self.halfedges[h].next
                if h == hid:
                    break

            if not face.boundary and len(reachable) < 3:
                errors.append(f"Face {fid}: only {len(reachable)} halfedges")

            orphans = he_by_face.get(fid, set()) - reachable
            if orphans:
                errors.append(f"Face {fid}: unreachable halfedges {orphans}")

        # -- vertex stars --
        he_by_vertex = {}
        for hid, he in self.halfedges.items():
            he_by_vertex.setdefault(he.vertex, set()).add(hid)

        for vid, vertex in self.vertices.items():
            if vertex.halfedge is None:
                errors.append(f"Vertex {vid}: no halfedge")
                continue
            if vertex.halfedge not in self.halfedges:
                errors.append(f"Vertex {vid}: halfedge {vertex.halfedge} missing")
                continue
            if self.halfedges[vertex.halfedge].vertex != vid:
                errors.append(
                    f"Vertex {vid}: halfedge {vertex.halfedge} -> vertex "
                    f"{self.halfedges[vertex.halfedge].vertex}")
                continue

            reachable = set()
            h = vertex.halfedge
            for _ in range(len(self.halfedges) + 1):
                reachable.add(h)
                twin = self.halfedges[h].twin
                if twin is None:
                    break
                h = self.halfedges[twin].next
                if h == vertex.halfedge:
                    break

            expected = he_by_vertex.get(vid, set())
            orphans = expected - reachable
            if orphans:
                errors.append(f"Vertex {vid}: {len(orphans)} unreachable halfedges")

        return errors
