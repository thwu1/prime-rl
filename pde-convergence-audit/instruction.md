A numerical PDE convergence benchmark is installed in `/app/`. It uses a hybrid Python/C architecture: performance-critical numerical kernels (tridiagonal solver, advection time-stepper) are implemented in C and loaded into Python solver modules via ctypes bindings. The benchmark covers four PDE problems — two Poisson equation variants (5-point and 9-point compact stencil), the 1D heat equation, and 1D linear advection — testing convergence behavior at grid resolutions N = 16, 32, 64, 128.

The benchmark is currently non-functional. The C kernel shared library has not been successfully built, and additional defects exist across multiple layers of the stack — build configuration, compiled kernels, foreign-function interface bindings, and Python solver logic. Investigate the full pipeline from compilation through solver execution, diagnose all failures, and apply corrections.

Run the corrected benchmark to produce `/app/results.json`. The output must satisfy:

- All four problems produce monotonically decreasing L2 errors across resolutions
- Each solver achieves a convergence order consistent with the theoretical accuracy of its underlying numerical scheme
- The higher-order compact scheme for the Poisson equation must be significantly more accurate than its lower-order counterpart at the finest resolution