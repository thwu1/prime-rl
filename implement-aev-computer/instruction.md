Create `/app/aev_pipeline.py`, a Python pipeline that computes Atomic Environment Vectors (AEVs) for organic molecules using the ANI neural network potential framework (Smith et al., Chemical Science 2017) and persists results in both HDF5 and SQLite formats.

When executed as `python3 /app/aev_pipeline.py`, the pipeline must:

Read molecular conformations from `/app/conformations.json`. Each molecule entry contains `elements` (element symbol list) and `coordinates` (Nx3 Angstrom positions). A `species_map` maps element symbols to integer species indices. Parse ANI symmetry function parameters from `/app/params.txt` (NeuroChem `.params` format). Compute AEVs for all molecules, numerically reproducing the NeuroChem/TorchANI reference. AEV length is 384 per atom (radial: indices 0–63, angular: indices 64–383). Only NumPy and the Python standard library may be used for AEV computation; ML frameworks (PyTorch, TensorFlow, JAX) and their wrappers are prohibited.

Write `/app/aev_output.h5` with this HDF5 structure:
- `/molecules/<name>/aev` — dataset, shape (n_atoms, 384), dtype float64, gzip compressed
- `/molecules/<name>/species` — dataset, shape (n_atoms,), dtype int64
- `/molecules/<name>/coordinates` — dataset, shape (n_atoms, 3), dtype float64
- `/molecules/<name>/` group attributes: `n_atoms` (int), `aev_length` (int, always 384)
- `/params/` group attributes: `Rcr` (float), `Rca` (float), `num_species` (int)
- `/metadata/` group attribute: `pipeline_version` = `"1.0"`

Write `/app/benchmark.db` as a SQLite database with tables:
- `molecules` — columns: `name TEXT PRIMARY KEY`, `n_atoms INTEGER NOT NULL`, `formula TEXT NOT NULL`, `radial_norm_mean REAL NOT NULL`, `radial_norm_std REAL NOT NULL`, `angular_norm_mean REAL NOT NULL`, `angular_norm_std REAL NOT NULL`, `sparsity REAL NOT NULL`, `max_element REAL NOT NULL`
- `atom_details` — columns: `molecule_name TEXT NOT NULL`, `atom_index INTEGER NOT NULL`, `species INTEGER NOT NULL`, `radial_l2_norm REAL NOT NULL`, `angular_l2_norm REAL NOT NULL`, with `PRIMARY KEY (molecule_name, atom_index)` and `FOREIGN KEY (molecule_name) REFERENCES molecules(name)`

`formula` uses Hill order (carbon first if present, then hydrogen, then remaining elements alphabetically; count omitted when 1). `sparsity` is the fraction of AEV matrix elements exactly equal to zero. Norm statistics (`radial_norm_mean`/`std`, `angular_norm_mean`/`std`) are mean and population standard deviation of per-atom L2 norms of the respective sub-AEV vectors. `radial_l2_norm`/`angular_l2_norm` in `atom_details` are per-atom L2 norms. All AEV values must match NeuroChem/TorchANI reference within 1e-5 absolute tolerance. The `hdf5-tools` and `sqlite3` CLI utilities are available in the environment.
