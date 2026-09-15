`/app/` contains a multi-file C project implementing a 3D Finite-Difference Time-Domain (FDTD) stencil benchmark. The project is designed to run two solver implementations on the same input, compare their numerical outputs, and write a structured JSON report.

The project has multiple issues preventing it from building and producing correct results.

When fully working, `make && ./fdtd3d` in `/app/` must exit 0 and produce:

- `/app/output_naive.bin` — numerically correct reference solver output (raw float32 array)
- `/app/output_tiled.bin` — optimized solver output matching the corrected reference within float32 precision
- `/app/results.json` — comparison report documenting numerical agreement between the two outputs

All source files, parameters, and interface specifications are in `/app/`.