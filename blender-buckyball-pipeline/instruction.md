A specification at `/app/targets.json` defines four polyhedra using Conway polyhedron notation. Each target is constructed by applying a chain of Conway operators to an icosahedral seed mesh. The four required operators are `dual`, `ambo` (rectification), `truncate`, and `kis` (kleetope).

Create `/app/conway_pipeline.py`: a Blender Python pipeline that reads the specification, implements all four Conway operators as direct mesh-topology transformations (not wrappers around Blender modifiers or `bmesh.ops.bevel`), generates each target polyhedron by composing the specified operator chain on a seed icosahedron, and exports the results. Each operator must correctly transform arbitrary convex polyhedra — not just hardcoded vertex tables for specific solids.

Execute with: `xvfb-run -a blender --background --python /app/conway_pipeline.py`

All output goes to `/app/output/`:

**`analysis.json`**: Top-level JSON object keyed by polyhedron name. Each entry contains: `vertex_count`, `edge_count`, `face_count`, `euler_characteristic` (must equal 2), `is_manifold` (must be true), `face_type_census` (object mapping polygon side-count as string key to number of such faces), `surface_area` (positive float), `volume` (positive float), `edge_length_std_dev` (non-negative float measuring edge-length uniformity), `max_face_planarity_error` (non-negative float measuring worst-case vertex deviation from the best-fit face plane).

**Per-polyhedron OBJ files**: `dodecahedron.obj`, `icosidodecahedron.obj`, `truncated_icosahedron.obj`, `pentakis_dodecahedron.obj`. Each must preserve native face polygon structure (no triangulation) with faces grouped by polygon type under distinct materials.

**`scene_render.png`**: Rendered image at exactly 1280×720 pixels showing all four polyhedra arranged in a single scene.