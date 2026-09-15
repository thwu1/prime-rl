The `/app/` directory contains a physically-based rendering pipeline that generates DFG lookup tables for image-based lighting. The pipeline uses performance-critical BRDF kernels implemented in C (`brdf_kernel.c`), compiled into a shared library (`libbrdf.so`), and called from Python via `ctypes` bindings.

The pipeline is broken across multiple layers:

**Build system (`Makefile`)**: Fails to produce a usable `libbrdf.so` shared library. The build configuration produces the wrong type of binary.

**C BRDF kernels (`brdf_kernel.c`)**: The GGX NDF, Smith-GGX visibility, Schlick Fresnel, Charlie NDF, and GGX importance sampling contain mathematical errors. The correct formulas are documented in `/app/spec.md`.

**Python-C bridge (`ffi_bridge.py`)**: The `ctypes` bindings for loading and calling the C library functions are unimplemented stubs.

**DFG integrators (`integrators.py`)**: Three importance sampling strategies (GGX, cosine-weighted hemisphere, uniform hemisphere) and a cloth integrator (Charlie + Neubelt) are unimplemented.

**Convergence analysis (`convergence.py`)**: The framework for evaluating and ranking the convergence behavior of different sampling strategies across roughness bands is incomplete.

**Pipeline orchestrator (`pipeline.py`)**: The LUT generation function is unimplemented.

Fix all issues and complete all implementations so that `python3 /app/pipeline.py` succeeds, producing `/app/convergence_report.json` with strategy RMSE comparisons per roughness band and `/app/dfg_lut.json` with accurate multi-model DFG values.