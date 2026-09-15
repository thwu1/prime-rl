Genomic data files in `/app/` contain variant calls from a sequencing experiment against a synthetic reference genome. The raw VCF has not undergone quality control and contains data integrity issues typical of production sequencing pipelines.

Build a pipeline that performs quality control on the raw VCF and produces functional variant effect annotations for each clean variant.

## Input files

- `/app/reference.fa` — Reference genome (FASTA, not indexed)
- `/app/annotations.gff3` — Gene model annotations (GFF3 with gene/mRNA/exon/CDS feature hierarchy)
- `/app/variants.vcf` — Raw variant calls (VCF 4.2)

## Required outputs

**`/app/results/qc_report.json`** — JSON documenting quality issues found and resolved in the raw VCF:

```json
{
  "ref_mismatches": "<int: variants where VCF REF allele does not match the reference genome>",
  "multiallelic_split": "<int: multi-allelic records decomposed into biallelic>",
  "indels_realigned": "<int: indel variants whose genomic position changed during normalization>",
  "total_input_variants": "<int: data lines in the raw input VCF>",
  "total_clean_variants": "<int: variant records remaining after all QC steps>"
}
```

**`/app/results/variant_effects.tsv`** — Tab-separated file with header and one row per clean variant (sorted by POS), columns:

| Column | Description |
|--------|-------------|
| CHROM | Chromosome |
| POS | 1-based position |
| REF | Reference allele |
| ALT | Alternative allele |
| GENE | Gene Name attribute from GFF3, or `.` if intergenic |
| EFFECT | Functional effect classification |
| CODON_REF | Reference codon at mRNA level, or `.` |
| CODON_ALT | Alternative codon at mRNA level, or `.` |
| AA_REF | Reference amino acid (1-letter code), or `.` |
| AA_ALT | Alternative amino acid (1-letter, `*` for stop), or `.` |
| AA_POS | 1-based amino acid position in the protein, or `.` |

EFFECT must be one of: `synonymous_variant`, `missense_variant`, `stop_gained`, `frameshift_variant`, `splice_donor_variant`, `splice_acceptor_variant`, `intron_variant`, `intergenic_variant`

**`/app/results/summary.json`** — JSON with:

```json
{
  "effect_counts": {"<effect_type>": "<count>"},
  "titv_ratio": "<float: transition/transversion ratio for SNPs only, 2 decimal places>",
  "genes_affected": ["<sorted list of gene names with at least one CDS-level variant>"]
}
```