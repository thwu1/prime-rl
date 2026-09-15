Build a mesh decimation pipeline at `/app/` that reduces triangle mesh face counts while preserving geometric quality and manifold topology.

**`/app/simplify.py`** — A CLI stub exists; implement the decimation logic.
`python3 /app/simplify.py <input.obj> <target_face_count> <output.obj>`

**`/app/Makefile`** — Create from scratch. `make -C /app all` must: process every `.obj` in `/app/meshes/`, decimate each to half its current face count (min 4 faces), write results to `/app/output/`, then run validation. Target face counts must be derived by piping `mesh_stats.py` JSON through `jq`.

**`/app/validate.sh`** — Create from scratch. For each mesh in `/app/output/`, pipe `mesh_stats.py` JSON output through `jq` to verify `is_valid` is `true` and `euler_characteristic` is `2`. Exit nonzero on any failure.

Decimated mesh constraints:
- Valid closed manifold (zero errors from `/app/halfedge.py` validation)
- Face count at or below target, never below 4
- V - E + F = 2
- Vertices inside the original mesh's bounding box
- Loadable via `/app/obj_io.py`

Available libraries at `/app/`: `halfedge.py` (halfedge data structure with traversal, modification, and validation), `obj_io.py` (OBJ I/O), `mesh_stats.py` (JSON mesh statistics). Meshes at `/app/meshes/`.