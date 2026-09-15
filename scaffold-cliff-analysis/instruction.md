The `/app/project/` directory contains an incomplete kinase inhibitor discovery project with raw, uncurated screening data spread across multiple files and formats. The project includes a pipeline configuration and methodology documentation that describe the intended analysis approach and parameters.

Implement the SAR landscape analysis pipeline and produce all required outputs in `/app/results/`. The raw data contains quality issues that must be identified and resolved before analysis can proceed.

Required output files:

- **`tanimoto_matrix.csv`**: Full symmetric pairwise similarity matrix. Compound IDs as both header row and index column.

- **`activity_cliffs.csv`**: Columns: `cpd1`, `cpd2`, `similarity`, `delta_pIC50`, `sali_score`. One row per detected cliff pair, ordered so `cpd1 < cpd2`.

- **`scaffolds.csv`**: Columns: `compound_id`, `canonical_smiles`, `murcko_scaffold`. One row per compound surviving data curation.

- **`scaffold_stats.csv`**: Columns: `scaffold`, `n_compounds`, `mean_pIC50`, `std_pIC50`. One row per unique scaffold.

- **`summary.json`**: Keys: `n_compounds`, `n_unique_scaffolds`, `n_activity_cliffs`, `n_cliff_generators`, `max_sali` (4 decimal places), `median_cliff_score` (4 decimal places).