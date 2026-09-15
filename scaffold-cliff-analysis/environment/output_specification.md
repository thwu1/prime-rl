# Output Specification

All output files must be written to the configured output directory.

## tanimoto_matrix.csv

Full pairwise compound similarity matrix.

- Compound IDs as both the header row and the first (index) column
- Values rounded per configuration

## activity_cliffs.csv

Columns: `cpd1`, `cpd2`, `similarity`, `delta_pIC50`, `sali_score`

- One row per detected cliff pair
- Pairs ordered lexicographically (cpd1 < cpd2)
- Pairs with identical fingerprints are excluded from the report
- Values rounded per configuration

## scaffolds.csv

Columns: `compound_id`, `canonical_smiles`, `murcko_scaffold`

- One row per analyzed compound

## scaffold_stats.csv

Columns: `scaffold`, `n_compounds`, `mean_pIC50`, `std_pIC50`

- One row per unique scaffold
- Sample standard deviation (ddof=1) for multi-compound groups, 0.0 for singletons
- Values rounded per configuration

## summary.json

JSON object with the following keys:

- `n_compounds`: total compounds in analysis
- `n_unique_scaffolds`: distinct scaffolds found
- `n_activity_cliffs`: number of cliff pairs detected
- `n_cliff_generators`: compounds classified as cliff generators
- `max_sali`: highest observed SALI value
- `median_cliff_score`: median per-compound cliff score
- Numeric values rounded per configuration where applicable
