The `/app/` directory contains a cross-field decomposition analysis pipeline implementing Continuum Power CCA (parameterized whitening + SVD-based coupled mode extraction). The system consists of:

- `/app/cross_decomp.py` — Core decomposition module providing data loading, whitening, SVD-based mode extraction, correlation patterns, Varimax/Promax rotation, and permutation-based significance testing
- `/app/pipeline.py` — Analysis runner that loads data and produces decomposition results
- `/app/validate_results.py` — Result validation script
- `/app/Makefile` — Pipeline orchestration (entry point: `make all`)
- `/app/data/fields.h5` — HDF5 data file containing paired climate fields in a hierarchical group structure

After a recent refactoring, the pipeline is broken. Running `make all` in `/app/` should produce validated decomposition results at `/app/results/decomposition.npz`, but currently fails. Multiple defects were introduced across different components whose effects cascade through the pipeline — upstream issues in data handling and whitening mask downstream errors in cross-covariance analysis and validation.

Diagnose and fix all defects so that the full pipeline runs correctly end-to-end and produces mathematically valid results. Function signatures and return value structures in `cross_decomp.py` must remain unchanged.