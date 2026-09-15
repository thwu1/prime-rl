## Environment

Files in `/app/`:
- `surface_code.stim` — distance-5 rotated surface code memory-X circuit (depolarizing noise, p=0.01)
- `surface_code.dem` — its detector error model
- `shots.b8` — 500 pre-recorded syndrome measurements (stim b8 format)
- `config.json` — keys: `num_detectors`, `num_observables`, `num_shots`, `distance`, `noise_rate`, `rounds`
- `test.dem` — small reference DEM for study

Pre-installed: `stim==1.14.0`, `numpy==2.1.3`, `scipy==1.14.1`.

## Deliverables

Create two Python modules in `/app/`:

### `/app/dem_to_matrices.py`

Export a dataclass `DemMatrices` with these fields (all matrix fields must be `scipy.sparse.csc_matrix`; `priors` must be `numpy.ndarray`):
- `check_matrix` — shape (num_detectors, num_error_mechanisms)
- `observables_matrix` — shape (num_observables, num_error_mechanisms)
- `edge_check_matrix` — shape (num_detectors, num_edges), where edges are degree-≤2 components from `^`-separated decomposition
- `edge_observables_matrix` — shape (num_observables, num_edges)
- `hyperedge_to_edge_matrix` — shape (num_edges, num_error_mechanisms)
- `priors` — shape (num_error_mechanisms,), per-mechanism error probabilities

Export a function `detector_error_model_to_check_matrices(dem: stim.DetectorErrorModel) -> DemMatrices`.

An error mechanism is uniquely identified by its detector set — the symmetric difference of all detector groups separated by `^` in each DEM `error` instruction. Observables are also tracked per mechanism and per edge via symmetric difference of the observable groups. When the same mechanism (same detector set) appears in multiple `error` instructions, their probabilities must be combined correctly as independent noise sources. Mechanisms that share the same detector set but appear in separate instructions are the same mechanism and their column in the matrices must not be duplicated.

### `/app/decoder.py`

Export a class `SyndromeDecoder`:
- `__init__(self, dem: stim.DetectorErrorModel)`
- `decode(self, syndrome: np.ndarray) -> np.ndarray` — binary predictions, shape `(num_observables,)`. A zero syndrome must return all-zero predictions.
- `decode_batch(self, shots: np.ndarray) -> np.ndarray` — binary predictions, shape `(num_shots, num_observables)`. All values must be in {0, 1}.

The decoder must outperform or match a standard `pymatching.Matching.from_detector_error_model` MWPM baseline on the 500-shot dataset (fewer or equal logical errors).

## Validation

- Matrix conversion is validated by constructing inline reference DEMs and checking exact matrix shapes, exact nonzero entry positions, and exact prior values after probability merging.
- On `surface_code.dem`, all matrix dimensions must be mutually consistent and agree with `config.json` (`num_detectors`, `num_observables`). All prior values must be in [0, 1].
- Decoder output shapes and binary constraints are verified, including the zero-syndrome case.
- The decoder is compared against a `pymatching.Matching.from_detector_error_model` MWPM baseline on `shots.b8`. It must achieve fewer or equal logical errors, and both decoders must produce nontrivial results (MWPM errors > 0, decoder errors < half of total shots).