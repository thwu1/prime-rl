Multiple sequence alignments for three protein families are at `/data/family_{1,2,3}.fasta` (FASTA format, reduced alphabet: A, C, D, E, F). Known residue-residue contacts for family 1 are at `/data/family_1_contacts.txt` (0-indexed position pairs, space-separated). No ground truth is provided for families 2 and 3.

A contact is a pair of positions (i, j) where |i - j| >= 5.

Build a pipeline that predicts residue-residue contacts from the sequence data and produces the three outputs described below.

## 1. `/app/results.json`

```json
{
  "family_1": {"top_contacts": [[i, j, score], ...], "precision_at_L": <float>, "n_sequences": <int>, "alignment_length": <int>},
  "family_2": {"top_contacts": [[i, j, score], ...], "precision_at_L": null, "n_sequences": <int>, "alignment_length": <int>},
  "family_3": {"top_contacts": [[i, j, score], ...], "precision_at_L": null, "n_sequences": <int>, "alignment_length": <int>}
}
```

Each family's `top_contacts` must contain at least L entries (L = alignment length), where each entry is an `[i, j, score]` triple with integer position indices and a numeric score. All contacts must be 0-indexed with both i and j in `[0, L)`, non-self (`i != j`), and long-range (`|i - j| >= 5`). Scores must be sorted in descending order (ties allowed).

`n_sequences` and `alignment_length` must exactly match the actual properties of each input FASTA file.

For family_1, `precision_at_L` must be a float in [0.0, 1.0] computed against the provided ground truth contacts, accurate to within 0.15 of the true precision@L. For families 2 and 3, set `precision_at_L` to `null`.

Minimum precision@L thresholds (evaluated against hidden ground truth): family_1 >= 0.50, family_2 >= 0.40, family_3 >= 0.30. At least two of the three families must achieve precision@L >= 0.45.

## 2. Contact map heatmaps via `gnuplot`

Use `gnuplot` (pre-installed at `/usr/bin/gnuplot`) to generate contact map heatmap images. You must write gnuplot scripts that read exported score matrices and produce PNG output using the `pngcairo` terminal. The required output files are:

- `/app/contact_map_family_1.png`
- `/app/contact_map_family_2.png`
- `/app/contact_map_family_3.png`

Each must be a valid PNG file (correct PNG magic bytes) of at least 1 KB, showing the L x L predicted contact score matrix as a color-mapped heatmap with residue positions on both axes.

## 3. Pipeline report (`/app/pipeline_report.tsv`)

Produce a tab-separated file at `/app/pipeline_report.tsv` with this exact header row followed by exactly three data rows (one per family, in order family_1, family_2, family_3):

```
family	n_sequences	alignment_length	neff	top_score	precision_at_L
```

Columns: `family` is the family name string. `n_sequences` and `alignment_length` are integers matching the input data. `neff` is the effective number of sequences after phylogenetic reweighting (float, must be > 0). `top_score` is the maximum predicted contact score for that family (float, must be > 0). For family_1, `precision_at_L` is the computed precision as a float in [0, 1]. For families 2 and 3, write `NA` in the `precision_at_L` column.