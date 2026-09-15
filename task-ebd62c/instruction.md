`/app/` contains a structural analysis pipeline for predicting critical buckling loads of 3D beam-column frames using a mixed C/Python architecture. Core matrix operations (elastic stiffness, coordinate transformation) are implemented in C (`/app/src/`) and exposed as a shared library. The higher-level analysis workflow lives in `/app/buckling_analysis.py`.

The system is non-functional due to three categories of defects:

1. The C shared library cannot be built from `/app/Makefile`
2. The Python ctypes wrapper for the C transformation function silently discards a parameter, producing incorrect results for non-axis-aligned members with asymmetric cross-sections
3. Five Python functions in the analysis pipeline are unimplemented stubs (`NotImplementedError`)

Fix all issues and complete the implementation so the pipeline accurately computes eigenvalue buckling loads. The mathematical specification is in `/app/SPECIFICATION.md`.