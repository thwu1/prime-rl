A noisy quantum device calibration database is at `/app/device.db` (SQLite) and experiment parameters are in `/app/experiment.toml`. The database contains a molecular Hamiltonian decomposed into Pauli terms, per-qubit noise characterization data, and available noise amplification factors. Examine the database schema and metadata for the noise model and measurement semantics.

Determine the measurement and extrapolation configuration that achieves the minimum total estimation variance of the Hamiltonian expectation value under the shot budget and extrapolation-point constraints.

Write:
- `/app/result.json` conforming to the schema in `/app/output_schema.json`
- `/app/allocation.csv` with columns `group,scale_factor,shots` — one row per (measurement group index, scale factor index) pair