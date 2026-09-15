A performance analysis framework at `/app/` models stencil computation performance across three HPC architectures (Intel Skylake, AMD EPYC, Fujitsu A64FX). The framework has bugs scattered across its Python modules, a defective C verification kernel, and a broken build system. Additionally, two core components are unimplemented stubs.

Fix all issues and implement the missing components. When everything is correct, the following must succeed and produce accurate results:

```
make -C /app all && python3 /app/analyze.py
```

The output file `/app/results.json` should contain correct per-architecture performance analysis and a verification checksum computed by the compiled C kernel shared library.

## Framework layout

- `/app/configs/*.json` — Architecture-specific machine parameters
- `/app/config_loader.py` — Config loading and unit normalization
- `/app/stencil.py` — Stencil FLOP and byte traffic counting
- `/app/roofline.py` — Performance prediction model with cache hierarchy
- `/app/scaling.py` — Parallel scaling laws and communication model
- `/app/metrics.py` — Cross-platform portability metric
- `/app/tiling.py` — Cache-aware 3D tile optimizer (**STUB**)
- `/app/analyze.py` — Full analysis pipeline producing `/app/results.json` (**STUB**)
- `/app/kernels/stencil_kernel.c` — C stencil verification kernel
- `/app/Makefile` — Build system for the C shared library