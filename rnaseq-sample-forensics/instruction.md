An RNA-seq experiment is stored in a SQLite database at `/app/data/experiment.db` with expression profiles for ~2000 genes across 24 samples, along with sample metadata, sequencing QC metrics, and laboratory notes in multiple relational tables. Pathway gene sets are at `/app/data/pathway_annotations.gmt`.

The experimental design has a structural problem relating processing batches to experimental conditions. Some samples may have been mislabeled during handling, and the treatment reagent identity was lost due to a labeling accident.

Four analysis pipelines at `/app/pipelines/` (`pipeline_a.py` through `pipeline_d.py`) each attempt to identify mislabeled samples and determine the perturbation type. Each contains a methodological flaw — some interact subtly with properties of this specific dataset.

Audit the experiment: explore the database schema, assess the experimental design for confounders, identify data quality anomalies at the gene level, evaluate each pipeline's methodology against the statistical properties of this dataset, and perform a correct analysis.

Write results to `/app/results.json`:
```json
{
  "pipeline_evaluations": {
    "pipeline_a": {"correct": false, "flaw_description": "<how the flaw interacts with this dataset's design>"},
    "pipeline_b": {"correct": false, "flaw_description": "<...>"},
    "pipeline_c": {"correct": false, "flaw_description": "<...>"},
    "pipeline_d": {"correct": false, "flaw_description": "<...>"}
  },
  "mislabeled_samples": ["Sample_XX", ...],
  "technical_outlier_genes": ["GENE_1", ...],
  "perturbation": "<perturbation type>",
  "confound_summary": "<explanation of the batch-condition confounding and its analytical implications>"
}
```

`mislabeled_samples`: sorted list of sample IDs whose metadata condition does not match their true biological condition.

`technical_outlier_genes`: sorted list of gene symbols exhibiting clear technical count artifacts — extreme values in specific samples inconsistent with biological variation patterns.

`perturbation`: short descriptor identifying the treatment applied.

`confound_summary`: explanation of the relationship between processing batch and experimental condition, and why this constrains which analytical approaches are valid.