Implement a syndrome decoder module at `/app/qec_pipeline.py` that processes Stim `DetectorErrorModel` noise models and predicts logical observable outcomes from detector syndrome measurements. The module must handle repetition codes and surface codes at realistic noise rates.

The test suite at `/tests/test_state.py` defines the required exports (`DemMatrices`, `dem_to_matrices`, `Decoder`), data structures, and acceptance criteria. All tests must pass.

Key requirements:
- Parse DEM error instructions including separator-delimited hyperedge decompositions
- Merge probabilities for duplicate error mechanisms
- Build sparse check matrices, observable matrices, and edge decomposition matrices
- Implement a graph-based minimum-weight matching decoder with virtual boundary nodes

Sample DEM files are at `/app/data/` for format reference. `stim` is pre-installed.

Your implementation must not depend on `pymatching`, `beliefmatching`, or `stimbposd`.