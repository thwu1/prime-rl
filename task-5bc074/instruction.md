A genomic variant annotation pipeline at `/app/pipeline/` is producing incorrect results. The pipeline processes 18 genomic variants from `/app/data/variants.vcf.gz` against a reference genome (`/app/data/reference.fa`, indexed) and gene annotations (`/app/data/genes.gff3`) to classify each variant's functional effect.

The pipeline (`/app/pipeline/run_pipeline.sh`) orchestrates `bcftools`, `bedtools`, and a custom Python effect classifier (`/app/pipeline/classify_effects.py`). Multiple bugs across the pipeline cause wrong, missing, or misannotated variants in the output.

Known-correct annotations for 6 representative variants are at `/app/expected/validation_subset.tsv`. These cover different variant classes and genes to help identify discrepancies.

Diagnose and fix all bugs in the pipeline. Write corrected annotations for all 18 variants to `/app/output/variant_effects.tsv` (tab-separated: CHROM, POS, REF, ALT, GENE, FEATURE, EFFECT, AA_CHANGE).