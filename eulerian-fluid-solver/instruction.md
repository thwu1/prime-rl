The directory `/app/` contains a 2D incompressible Eulerian fluid simulator that uses a MAC staggered grid. The performance-critical pressure solver and field interpolation are implemented in C (`/app/solver.c`), built as a shared library via `/app/Makefile`, and called from the Python orchestration layer (`/app/fluid.py`) through ctypes.

The project is non-functional across multiple layers — build system, foreign function interface, numerical kernels, and physics integration. Nothing runs out of the box.

Fix all defects in `/app/Makefile`, `/app/solver.c`, and `/app/fluid.py` so that the complete wind-tunnel simulation pipeline works correctly: the shared library builds and links as a position-independent shared object, the Python ctypes bindings match the C function signatures, the Gauss-Seidel pressure projection converges without memory errors, bilinear field interpolation respects the staggered-grid data layout for each field type, boundary forces are physically consistent, and passive smoke transport operates via semi-Lagrangian advection.

Do not alter C function signatures or the public Python API. Do not add new source files.