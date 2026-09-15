`/app/` contains a partially implemented GPU kernel performance analysis framework (`kernel_sim` Python package). It models how tile execution ordering in blocked matrix multiplication affects L2 cache utilization — analyzing the tradeoff between naive row-major scheduling and grouped/swizzled orderings used in production GPU kernels.

The entry point `/app/run_analysis.py` should produce a complete analysis report but currently crashes. Several methods across the package raise `NotImplementedError`. The codebase also contains at least one correctness bug that silently produces wrong numerical results even after all unimplemented methods are filled in.

Get the framework fully operational and produce a correct analysis at `/app/analysis.json` for:
- Matrix dimensions: M=4096, N=4096, K=2048
- Tile block sizes: 128x128x64
- Hardware configuration: `/app/configs/h100.json`