`/app/gm_ops.py` contains a Gaussian Mixture (GM) operations library skeleton for flow-matching generative models (GMFlow, arXiv 2504.05304). All core functions raise `NotImplementedError` and must be implemented. Mathematical specifications are in `/app/reference/theory.md`; a conceptual overview is in `/app/reference/overview.md`.

The function `gm_logpdf_c` requires a compiled C shared library at `/app/libgm_logpdf.so`. A C source skeleton is provided at `/app/gm_logpdf.c` and must be completed, compiled, and loaded via `ctypes`.

The helper functions `gm_to_sample` and `gm_to_mean` at the bottom of the file are correct and should not be modified.

Implement all operations so that the test suite passes.