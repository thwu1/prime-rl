A multi-omic regulatory genomics dataset in `/app/data/` contains motif specifications for 8 transcription factors (TFs), promoter DNA sequences, chromatin accessibility peaks, partial ChIP-seq validation data, and gene expression measurements.

**Data files:**

| File | Description |
|------|-------------|
| `motifs.meme` | Position Weight Matrices for TF_A through TF_H in standard MEME motif format. |
| `promoters_train.fa` | 150 promoter sequences (800 bp), FASTA format. |
| `promoters_test.fa` | 50 promoter sequences (800 bp), FASTA format. |
| `accessibility.bed` | ATAC-seq chromatin accessibility peaks across all 200 promoters, BED6 format. |
| `expression_train.tsv` | Tab-separated expression levels for training genes. |
| `chipseq_TFC.narrowPeak` | ChIP-seq peaks for one TF in ENCODE narrowPeak format. Can be used to calibrate motif scanning parameters. |
| `genome.sizes` | Promoter sizes for genomic interval tools. |

**Goal:** Reconstruct the regulatory network: determine each TF's regulatory role, identify the master regulator, discover cooperative or antagonistic interactions between TF pairs, and predict expression for the 50 test promoters. Not all TF binding events may be functionally relevant — the chromatin context matters.

## Required Outputs

Write the following files to `/app/results/`:

**`tf_roles.json`** — JSON mapping each TF name to `"activator"` or `"repressor"`. All 8 TFs must be present.

**`master_regulator.txt`** — Single line: the TF with the strongest regulatory effect.

**`predictions.tsv`** — Tab-separated file with columns `gene_id` and `predicted_expression` for all 50 test genes (GENE_151 through GENE_200).

**`functional_binding.bed`** — BED6 file of TF binding sites that are functionally relevant (considering chromatin accessibility). Columns: sequence_name, start, end, tf_name, score, strand. 0-based coordinates within each promoter. Must contain entries from all 8 TFs and at least 100 sites total.

**`regulatory_network.json`** — JSON object with keys: `"tf_roles"` (same as tf_roles.json), `"master_regulator"` (string), and `"interactions"` (array of objects, each with `"tf1"`, `"tf2"`, and `"type"` where type is `"cooperative"` or `"antagonistic"`). Must include any discovered TF-TF interactions that significantly affect expression beyond their individual contributions.

## Success Criteria

- At least 6 of 8 TF roles correctly classified
- Master regulator correctly identified
- Predicted test expression achieves R² >= 0.50
- Functional binding sites are in valid BED6 format, include all 8 TFs, and contain >= 100 entries
- Regulatory network includes the true cooperative TF pair interaction