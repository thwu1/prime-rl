"""
Halfedge mesh data structure for computational geometry.

Provides a halfedge-based mesh representation with construction from
indexed face lists, traversal, queries, and modification support.

"""

import numpy as np
from typing import List, Tuple, Optional, Dict


class Vertex:
    __slots__ = ['id', 'position', 'halfedge']

    def __init__(self, vid: int, position):
        self.id = vid
        self.position = np.array(position, dtype=np.float64)
        self.halfedge: Optional[int] = None


class Halfedge:
    __slots__ = ['id', 'twin', 'next', 'vertex', 'edge', 'face']

    def __init__(self, hid: int):
        self.id = hid
        self.twin: Optional[int] = None
        self.next: Optional[int] = None
        self.vertex: Optional[int] = None
        self.edge: Optional[int] = None
        self.face: Optional[int] = None


class Edge:
    __slots__ = ['id', 'halfedge']

    def __init__(self, eid: int):
        self.id = eid
        self.halfedge: Optional[int] = None


class Face:
    __slots__ = ['id', 'halfedge', 'boundary']

    def __init__(self, fid: int, boundary: bool = False):
        self.id = fid
        self.halfedge: Optional[int] = None
        self.boundary = boundary


class HalfedgeMesh:
    """
    Halfedge mesh data structure.

    Elements are stored in dictionaries keyed by integer IDs.
    Cross-references between elements use these integer IDs.

    Convention: halfedge.vertex is the SOURCE vertex (the vertex the
    halfedge leaves from). The TARGET vertex is halfedge.twin.vertex.
    Vertex circulation: for halfedge h leaving vertex v, the next
    outgoing halfedge from v is h.twin.next.
    """

    def __init__(self):
        self.vertices: Dict[int, Vertex] = {}
        self.halfedges: Dict[int, Halfedge] = {}
        self.edges: Dict[int, Edge] = {}
        self.faces: Dict[int, Face] = {}
        self._next_vid = 0
        self._next_hid = 0
        self._next_eid = 0
        self._next_fid = 0

    def _add_vertex(self, position) -> int:
        vid = self._next_vid; self._next_vid += 1
        self.vertices[vid] = Vertex(vid, position)
        return vid

    def _add_halfedge(self) -> int:
        hid = self._next_hid; self._next_hid += 1
        self.halfedges[hid] = Halfedge(hid)
        return hid

    def _add_edge(self) -> int:
        eid = self._next_eid; self._next_eid += 1
        self.edges[eid] = Edge(eid)
        return eid

    def _add_face(self, boundary=False) -> int:
        fid = self._next_fid; self._next_fid += 1
        self.faces[fid] = Face(fid, boundary)
        return fid

    # ----------------------------------------------------------------
    # Construction
    # ----------------------------------------------------------------

    @classmethod
    def from_indexed_faces(cls, positions, face_indices):
        """
        Build a halfedge mesh from vertex positions and face index lists.

        Args:
            positions: list of (x, y, z) tuples or lists
            face_indices: list of lists of vertex indices (CCW winding)

        Returns:
            HalfedgeMesh instance (with boundary faces for open meshes)
        """
        mesh = cls()

        for pos in positions:
            mesh._add_vertex(pos)

        pair_to_he: Dict[Tuple[int, int], int] = {}

        for face_verts in face_indices:
            fid = mesh._add_face()
            n = len(face_verts)
            he_ids = [mesh._add_halfedge() for _ in range(n)]

            mesh.faces[fid].halfedge = he_ids[0]

            for i in range(n):
                h = mesh.halfedges[he_ids[i]]
                h.vertex = face_verts[i]
                h.face = fid
                h.next = he_ids[(i + 1) % n]
                pair_to_he[(face_verts[i], face_verts[(i + 1) % n])] = he_ids[i]

            for i in range(n):
                vid = face_verts[i]
                if mesh.vertices[vid].halfedge is None:
                    mesh.vertices[vid].halfedge = he_ids[i]

        # Pair twins and create edges for interior half-edge pairs
        paired = set()
        for (v0, v1), hid in pair_to_he.items():
            if hid in paired:
                continue
            twin_key = (v1, v0)
            if twin_key in pair_to_he:
                tid = pair_to_he[twin_key]
                mesh.halfedges[hid].twin = tid
                mesh.halfedges[tid].twin = hid
                eid = mesh._add_edge()
                mesh.edges[eid].halfedge = hid
                mesh.halfedges[hid].edge = eid
                mesh.halfedges[tid].edge = eid
                paired.add(hid)
                paired.add(tid)

        # Handle boundary edges
        unpaired = [hid for hid in mesh.halfedges if mesh.halfedges[hid].twin is None]

        if unpaired:
            starts_at: Dict[int, int] = {}
            boundary_twin_ids = []

            for hid in unpaired:
                h = mesh.halfedges[hid]
                v_to = mesh.halfedges[h.next].vertex

                tid = mesh._add_halfedge()
                bt = mesh.halfedges[tid]
                bt.vertex = v_to
                bt.twin = hid
                h.twin = tid

                eid = mesh._add_edge()
                mesh.edges[eid].halfedge = hid
                h.edge = eid
                bt.edge = eid

                starts_at[v_to] = tid
                boundary_twin_ids.append(tid)

            # Link boundary twins into loops and create boundary faces
            visited = set()
            for bt_start in boundary_twin_ids:
                if bt_start in visited:
                    continue
                bfid = mesh._add_face(boundary=True)
                mesh.faces[bfid].halfedge = bt_start

                current = bt_start
                while current not in visited:
                    visited.add(current)
                    bt = mesh.halfedges[current]
                    bt.face = bfid
                    dest = mesh.halfedges[bt.twin].vertex
                    bt.next = starts_at[dest]
                    current = bt.next

        return mesh

    # ----------------------------------------------------------------
    # Traversal helpers
    # ----------------------------------------------------------------

    def he_target(self, hid: int) -> int:
        """Target (destination) vertex of halfedge hid."""
        return self.halfedges[self.halfedges[hid].twin].vertex

    def vertex_halfedges(self, vid: int) -> List[int]:
        """All outgoing halfedge IDs from vertex vid."""
        result = []
        start = self.vertices[vid].halfedge
        if start is None:
            return result
        current = start
        for _ in range(len(self.halfedges)):  # safety bound
            result.append(current)
            twin = self.halfedges[current].twin
            current = self.halfedges[twin].next
            if current == start:
                break
        return result

    def vertex_vertices(self, vid: int) -> List[int]:
        """IDs of all vertices adjacent to vid."""
        return [self.he_target(hid) for hid in self.vertex_halfedges(vid)]

    def vertex_faces(self, vid: int) -> List[int]:
        """IDs of all adjacent non-boundary faces."""
        return [self.halfedges[hid].face
                for hid in self.vertex_halfedges(vid)
                if not self.faces[self.halfedges[hid].face].boundary]

    def vertex_edges(self, vid: int) -> List[int]:
        """IDs of all edges incident to vertex."""
        return [self.halfedges[hid].edge for hid in self.vertex_halfedges(vid)]

    def face_halfedges(self, fid: int) -> List[int]:
        """All halfedge IDs around face fid."""
        result = []
        start = self.faces[fid].halfedge
        current = start
        for _ in range(len(self.halfedges)):
            result.append(current)
            current = self.halfedges[current].next
            if current == start:
                break
        return result

    def face_vertices(self, fid: int) -> List[int]:
        """Vertex IDs around face fid."""
        return [self.halfedges[hid].vertex for hid in self.face_halfedges(fid)]

    def edge_vertices(self, eid: int) -> Tuple[int, int]:
        """The two endpoint vertex IDs of edge eid."""
        h = self.edges[eid].halfedge
        return (self.halfedges[h].vertex, self.he_target(h))

    def edge_faces(self, eid: int) -> List[int]:
        """Face IDs on both sides of edge eid."""
        hid = self.edges[eid].halfedge
        h = self.halfedges[hid]
        return [h.face, self.halfedges[h.twin].face]

    # ----------------------------------------------------------------
    # Queries
    # ----------------------------------------------------------------

    def n_vertices(self) -> int:
        return len(self.vertices)

    def n_edges(self) -> int:
        return len(self.edges)

    def n_faces(self) -> int:
        """Count non-boundary faces."""
        return sum(1 for f in self.faces.values() if not f.boundary)

    def is_boundary_vertex(self, vid: int) -> bool:
        for hid in self.vertex_halfedges(vid):
            if self.faces[self.halfedges[hid].face].boundary:
                return True
        return False

    def is_boundary_edge(self, eid: int) -> bool:
        hid = self.edges[eid].halfedge
        h = self.halfedges[hid]
        return (self.faces[h.face].boundary or
                self.faces[self.halfedges[h.twin].face].boundary)

    def face_normal(self, fid: int) -> np.ndarray:
        """Unit normal of face fid."""
        vids = self.face_vertices(fid)
        if len(vids) < 3:
            return np.array([0., 0., 1.])
        p0 = self.vertices[vids[0]].position
        p1 = self.vertices[vids[1]].position
        p2 = self.vertices[vids[2]].position
        n = np.cross(p1 - p0, p2 - p0)
        length = np.linalg.norm(n)
        if length < 1e-15:
            return np.array([0., 0., 1.])
        return n / length

    def face_area(self, fid: int) -> float:
        """Area of a triangular face."""
        vids = self.face_vertices(fid)
        if len(vids) < 3:
            return 0.0
        p0 = self.vertices[vids[0]].position
        p1 = self.vertices[vids[1]].position
        p2 = self.vertices[vids[2]].position
        return 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0))

    # ----------------------------------------------------------------
    # Modification
    # ----------------------------------------------------------------

    def remove_vertex(self, vid: int):
        del self.vertices[vid]

    def remove_halfedge(self, hid: int):
        del self.halfedges[hid]

    def remove_edge(self, eid: int):
        del self.edges[eid]

    def remove_face(self, fid: int):
        del self.faces[fid]

    # ----------------------------------------------------------------
    # Validation
    # ----------------------------------------------------------------

    def validate(self) -> List[str]:
        """Check mesh validity. Returns list of error strings (empty = valid)."""
        errors = []

        for hid, h in self.halfedges.items():
            if h.twin is None or h.twin not in self.halfedges:
                errors.append(f"HE {hid}: bad twin {h.twin}")
            elif self.halfedges[h.twin].twin != hid:
                errors.append(f"HE {hid}: twin's twin != self")

            if h.next is None or h.next not in self.halfedges:
                errors.append(f"HE {hid}: bad next {h.next}")

            if h.vertex is None or h.vertex not in self.vertices:
                errors.append(f"HE {hid}: bad vertex {h.vertex}")

            if h.edge is None or h.edge not in self.edges:
                errors.append(f"HE {hid}: bad edge {h.edge}")

            if h.face is None or h.face not in self.faces:
                errors.append(f"HE {hid}: bad face {h.face}")

        for vid, v in self.vertices.items():
            if v.halfedge is None or v.halfedge not in self.halfedges:
                errors.append(f"V {vid}: bad halfedge {v.halfedge}")
            elif self.halfedges[v.halfedge].vertex != vid:
                errors.append(f"V {vid}: halfedge doesn't start here")

        for eid, e in self.edges.items():
            if e.halfedge is None or e.halfedge not in self.halfedges:
                errors.append(f"E {eid}: bad halfedge {e.halfedge}")
            elif self.halfedges[e.halfedge].edge != eid:
                errors.append(f"E {eid}: halfedge has wrong edge")

        for fid, f in self.faces.items():
            if f.halfedge is None or f.halfedge not in self.halfedges:
                errors.append(f"F {fid}: bad halfedge {f.halfedge}")
                continue
            count = 0
            current = f.halfedge
            while True:
                if current not in self.halfedges:
                    errors.append(f"F {fid}: broken cycle")
                    break
                if self.halfedges[current].face != fid:
                    errors.append(f"F {fid}: HE {current} wrong face")
                current = self.halfedges[current].next
                count += 1
                if count > len(self.halfedges):
                    errors.append(f"F {fid}: infinite cycle")
                    break
                if current == f.halfedge:
                    break
            if count < 3:
                errors.append(f"F {fid}: only {count} edges")

        return errors

    # ----------------------------------------------------------------
    # Export
    # ----------------------------------------------------------------

    def to_indexed_faces(self):
        """Export as (positions_list, faces_list)."""
        vid_to_idx = {}
        positions = []
        for vid in sorted(self.vertices.keys()):
            vid_to_idx[vid] = len(positions)
            positions.append(self.vertices[vid].position.tolist())

        faces = []
        for fid in sorted(self.faces.keys()):
            if self.faces[fid].boundary:
                continue
            vids = self.face_vertices(fid)
            faces.append([vid_to_idx[vid] for vid in vids])

        return positions, faces
