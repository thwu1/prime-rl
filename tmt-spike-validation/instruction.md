Dataset PXD000001 in the PRIDE Archive is a TMT 6-plex spike-in experiment. Build `/app/pipeline.py` that queries the PRIDE REST API, downloads the relevant data files, and produces a quantification assessment at `/app/results.json`.

The pipeline must locate the project's mzTab peptide identification file and FASTA protein sequence database through the PRIDE API file-listing endpoints, download them, and perform the analyses described below.

`/app/results.json` schema:

```json
{
  "project_accession": "PXD000001",
  "project_title": "<from API>",
  "total_peptides": 0,
  "total_proteins": 0,
  "valid_tryptic_peptides": 0,
  "invalid_tryptic_peptides": 0,
  "tryptic_coverage_pct": 0.0,
  "protein_classifications": {
    "erwinia": [], "enolase_spike": [], "bsa_spike": [],
    "phosb_spike": [], "cytc_spike": [], "unclassified": []
  },
  "protein_ratios": {"<accession>": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
  "peptide_masses": {"<sequence>": 0.0},
  "spike_expected_ratios": {"<category>": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
  "ratio_rmsd": {"<category>": 0.0},
  "per_protein_cv": {"<accession>": 0.0}
}
```

Constraints:

- `total_peptides`: count of peptide identification rows from the mzTab file with associated TMT quantification.
- `total_proteins`: distinct proteins having at least one peptide with all six TMT channels positive.
- Enzymatic digest validation: cross-reference observed peptides against theoretical digest products of their parent proteins from the FASTA. Determine the protease from the experimental context. Allow 0–2 missed cleavages, minimum peptide length 6. Only peptides whose accession appears in the FASTA are checked. `tryptic_coverage_pct` = valid / (valid + invalid) * 100, rounded to 2 dp.
- `peptide_masses`: monoisotopic neutral mass for each observed peptide sequence, rounded to 4 dp.
- `protein_ratios`: six-element arrays normalized to channel 1. Only peptides with all six channels positive contribute.
- `protein_classifications`: assign each quantified protein to one of the six categories by determining the spike-in protein identities from the project description returned by the API. Lists sorted alphabetically.
- `spike_expected_ratios`: the designed TMT channel ratios for each spike-in category and the background organism, extracted from the project description. Normalized to channel 1, rounded to 4 dp. Keys: `erwinia`, `enolase_spike`, `bsa_spike`, `phosb_spike`, `cytc_spike`.
- `ratio_rmsd`: for each category in `spike_expected_ratios`, the root-mean-square deviation between the mean observed protein ratios for that category and the expected ratios, across all six channels. Rounded to 4 dp.
- `per_protein_cv`: for proteins with >=3 peptides contributing to ratio analysis, the per-channel coefficient of variation of normalized ratios across peptides, averaged over all six channels. Rounded to 4 dp.

Run: `python3 /app/pipeline.py`
