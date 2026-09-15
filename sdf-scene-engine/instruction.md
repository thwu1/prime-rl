A 3D geometric scene is defined in `/app/scene.json` as a hierarchy of shapes and operations. The format specification — including all primitive definitions, operation semantics, query processing requirements, and required output files — is documented in `/app/spec.md`.

Input files:
- `/app/scene.json` — scene definition
- `/app/queries.json` — 60 spatial queries against the scene
- `/app/camera.json` — rendering camera parameters

Produce all output files specified in `/app/spec.md`. Numerical results must be correct within the tolerances defined by the test suite.