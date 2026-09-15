You are given a synthetic bulk RNA-seq dataset where each sample is a mixture of multiple cell types. The data contains batch effects and condition-dependent changes in both cell type composition and gene expression.

## Data

- `/app/counts.csv`: Bulk RNA-seq expression matrix (genes x samples)
- `/app/signature.csv`: Reference cell type signature matrix (genes x cell types)
- `/app/metadata.csv`: Sample metadata with columns `sample_id`, `condition`, `batch`

## Task

Perform cell type deconvolution using the reference signature matrix, identify which cell types are differentially abundant between conditions, and run differential expression analysis that correctly separates true per-gene expression changes from apparent changes driven by shifts in cell type composition.

## Required Output

Write all results to `/app/results/`:

1. `proportions.csv`: Estimated cell type proportions. Rows = samples (matching sample IDs from metadata), columns = cell types (matching column names from signature matrix). Values must be non-negative and sum to approximately 1 per sample.

2. `da_results.csv`: Differential abundance testing between conditions. Columns: `cell_type`, `log2fc` (positive means higher in treatment), `pvalue`, `padj` (Benjamini-Hochberg corrected).

3. `de_results.csv`: Composition-aware differential expression results for all genes. Columns: `gene`, `log2fc`, `pvalue`, `padj`. These must reflect true expression changes after accounting for cell type composition shifts and batch effects.

4. `significant_genes.txt`: Gene names with `padj < 0.05` from the composition-aware DE analysis, one per line.

## Key Constraint

Naive differential expression (ignoring cell type composition) will yield misleading results. Many apparent expression changes between conditions are artifacts of shifting cell type proportions, not true per-gene regulatory changes. Your analysis must disentangle these effects.