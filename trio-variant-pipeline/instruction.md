A clinical genomics laboratory has deployed a variant analysis pipeline for investigating rare Mendelian diseases in family trios. The pipeline at `/app/pipeline/run.sh` (with configuration in `/app/pipeline/vcfanno.toml` and `/app/pipeline/trio.ped`) uses `vcfanno` for multi-source variant annotation and `slivar` for trio-based inheritance model filtering (de novo, autosomal recessive, compound heterozygous), followed by candidate variant ranking.

Whole-exome sequencing data for a trio is available at `/app/data/trio.vcf.gz`:

- **HG002**: proband (affected male)
- **HG003**: father (unaffected)
- **HG004**: mother (unaffected)

Annotation resources:

- `/app/data/popfreq.vcf.gz` — population allele frequencies (INFO/AF)
- `/app/data/regions.bed.gz` — regional functional impact scores (column 4)

The pipeline executes without errors but has not been validated against clinical-grade analysis standards. Perform a comprehensive audit of the entire pipeline — annotation configuration, trio filter expressions, inheritance model coverage, and variant prioritization logic — against ACMG/AMP-aligned rare disease analysis best practices. Correct all deficiencies found across configuration files, filtering logic, evidence criteria, and ranking methodology.

After correcting the pipeline, re-run it to produce:

1. The re-annotated VCF at `/app/annotated.vcf.gz`. The downstream slivar filter expressions reference population frequency as `pop_af` — the annotated VCF's INFO header must contain a field with this name.

2. Results in `/app/results/`:
   - `denovo_count.txt` — count of de novo variants passing quality, evidence, and frequency filters (plain integer)
   - `recessive_count.txt` — count of autosomal recessive variants passing all filters (plain integer)
   - `compound_het_genes.txt` — gene(s) harboring compound heterozygous pairs, one per line, sorted alphabetically
   - `top_candidate.txt` — highest-priority causal variant formatted as `chr:pos:ref:alt`