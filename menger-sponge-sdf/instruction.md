Implement `/app/lattice_generator.py` using the `manifold3d` Python library to produce a gyroid TPMS (triply-periodic minimal surface) lattice structure within a rhombic dodecahedron bounding shape that achieves a specified target volume fraction.

The specification at `/app/spec.json` defines parameters: `bounding_size`, `num_periods`, `target_volume_fraction`, `volume_fraction_tolerance`, and `mesh_segments_per_period`.

## Required API

`/app/lattice_generator.py` must expose these callable functions:

- `gyroid_sdf(x, y, z)` → float: the standard gyroid implicit function evaluated at (x, y, z)
- `build_bounding_shape(size)` → `Manifold`: a rhombic dodecahedron whose volume scales cubically with `size`
- `build_lattice(iso_thickness, size, num_periods, mesh_segments)` → `Manifold`: the gyroid lattice clipped to the bounding shape; larger `iso_thickness` must produce greater volume fraction
- `find_iso_thickness(target_vf, tolerance, size, num_periods, mesh_segments)` → float: the `iso_thickness` value that achieves volume fraction (= lattice volume / bounding volume) within `tolerance` of `target_vf`
- `generate_lattice(spec_path)` → dict: reads the spec, produces the lattice, writes `/app/result.json`, returns the result dict

When run as `python3 /app/lattice_generator.py`, must call `generate_lattice("/app/spec.json")`.

## Output: `/app/result.json`

JSON with keys: `iso_thickness` (float), `volume_fraction` (float), `solid_volume` (float), `bounding_volume` (float), `surface_area` (float), `genus` (int), `status` (str — `"NoError"` for valid manifold), `num_vert` (int), `num_tri` (int).

## Success Criteria

- Valid manifold mesh: status `"NoError"`, positive genus, even triangle count
- `volume_fraction` within `volume_fraction_tolerance` of `target_volume_fraction`
- `volume_fraction` equals `solid_volume / bounding_volume`
- All geometric quantities positive; solid volume strictly less than bounding volume