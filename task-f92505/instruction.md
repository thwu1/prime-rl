A signed distance field rendering pipeline is installed at `/app/`. It uses a C shared library for SDF primitive evaluation (source in `/app/src/`, header `/app/src/sdf.h`), Python ctypes FFI bindings (`/app/bindings.py`), and a Python sphere-tracing renderer. The library build is managed by `/app/Makefile`.

Build the library with `make` in `/app/` and run the pipeline with `python3 /app/main.py`. It should produce:

- `/app/distances.csv` — signed distance values for query points in `/app/eval_points.csv`
- `/app/render.ppm` — a 256x192 P6 PPM image of the scene

The pipeline currently has defects across its toolchain — in the C source, build configuration, and Python scene logic. Some functions are missing correct implementations entirely (containing only placeholder approximations that produce wrong results), while others have subtle mathematical or logical errors. Reference SDF values for 130 sample points are in `/app/reference_samples.csv` (format: `x,y,z,expected_distance`).

Fix all defects so the pipeline builds cleanly, the computed SDF distances match the reference data, and the rendered image is geometrically correct with proper lighting.