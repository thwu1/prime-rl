The script `/app/build.py` uses the `manifold3d` Python library to construct a gyroid module solid and write its topological and geometric properties to `/app/result.json`. The target properties are specified in `/app/target.json`.

Running `python3 /app/build.py` currently produces geometrically incorrect output that does not match the target. The solid should be a gyroid-based TPMS (triply-periodic minimal surface) shell bounded by a rhombic dodecahedron, with size parameter 20.

Produce a correct `/app/result.json` by fixing `/app/build.py`. The `manifold3d` package is not pre-installed.