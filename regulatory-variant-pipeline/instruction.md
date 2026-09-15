The directory `/app/data/` contains genomic annotations and variant calls from a sequencing study. The data was assembled from multiple upstream pipelines and sources; it contains formatting inconsistencies and quality issues that must be identified and resolved before analysis can proceed.

Your task is to identify **regulatory variants**: variants that overlap **active regulatory regions** of the genome.

**Active regulatory regions** are defined as genomic intervals satisfying ALL of the following:

1. Annotated as either a **promoter** OR an **enhancer**
2. Overlap a **CpG island**
3. Do **not** overlap a **repeat element**
4. Are within **2000 bp** of an **expressed gene** (FPKM ≥ 10 in the expression data)

"Within 2000 bp of a gene" means the regulatory region intersects the gene body extended by 2000 bp on each side (clipped to chromosome boundaries using the genome file).

Produce the following output files:

- `/app/results/regulatory_variants.bed` — BED file of variants falling in active regulatory regions. Sorted by position, deduplicated, using standard chromosome naming (e.g., `chr1`).
- `/app/results/active_regions.bed` — BED3 file of the final active regulatory regions (sorted, merged).
- `/app/results/summary.txt` — Plain text with exactly these key=value lines:
  ```
  regulatory_variant_count=<N>
  total_variant_count=<N>
  active_region_count=<N>
  active_region_total_bp=<N>
  fraction_regulatory=<X.XXXX>
  ```
  `total_variant_count` is the number of unique variants after normalization. `fraction_regulatory` is `regulatory_variant_count / total_variant_count` rounded to 4 decimal places.