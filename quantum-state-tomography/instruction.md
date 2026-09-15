Experimental quantum tomographic measurement data has been collected for three unknown multi-qubit quantum states. Your task is to reconstruct each state's density matrix from the raw measurements and characterize its entanglement properties.

## Data Sources

Measurement counts are stored in a relational SQLite database at `/data/tomography.db`. The database uses a normalized multi-table schema with foreign key relationships. You must discover the schema, understand the table relationships, and write appropriate queries to extract per-state measurement records grouped by Pauli basis setting.

Per-qubit readout calibration data is stored as raw binary files under `/data/calibration/`. The binary format, byte layout, and directory structure are documented in `/data/manifest.yaml`.

Full experiment configuration -- including state metadata, calibration file paths, binary format specification, and required output schema -- is in `/data/manifest.yaml`.

## Required Output

For each state, write to `/app/results/<state_name>/`:

- `density_matrix_real.csv`: Real part of the reconstructed density matrix (comma-separated, no header, no index)
- `density_matrix_imag.csv`: Imaginary part (same format)
- `density_matrix.png`: Visualization of the density matrix (heatmap or Hinton diagram showing magnitude of elements)
- `properties.json` containing:
  - For 2-qubit states: `purity` (float), `concurrence` (float), `is_entangled` (bool), `entanglement_type` (string: `"maximally_entangled"` if concurrence > 0.9, `"partially_entangled"` if 0 < concurrence <= 0.9, `"separable"` otherwise)
  - For the 3-qubit state: `purity` (float), `is_entangled` (bool), `is_genuine_multipartite_entangled` (bool -- true iff entangled across every bipartite cut), `min_bipartite_negativity` (float -- minimum negativity over all single-qubit-vs-rest bipartitions)

Additionally, write a summary database to `/app/results/summary.db` following the schema specified in the manifest.

## Constraints

- All reconstructed density matrices must be physically valid: Hermitian, positive semidefinite, unit trace.
- Raw measurement counts are corrupted by readout errors; use the provided calibration data to correct them.