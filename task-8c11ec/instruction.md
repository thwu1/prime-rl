A synthetic chromosome has three competing exclusion strategies for constructing GIAB-style genomic benchmark regions. A curated truth set classifies each variant as `validated_true` or `validated_false`. Determine which strategy yields the highest-quality benchmark, diagnose which exclusion step in the best strategy most harms quality, and produce an optimized configuration where all validated_true variants are retained in and all validated_false variants are excluded from the final benchmark regions.

Benchmark quality composite score: `0.4 × sensitivity + 0.4 × specificity + 0.2 × coverage_fraction`.

## Data

- `/app/reference.fa`, `/app/reference.fa.fai` — Reference (chr_test, 500,000 bp)
- `/app/calls.vcf.gz`, `/app/calls.vcf.gz.tbi` — 45 variant calls
- `/app/annotations/` — Annotation BED files
- `/app/strategies/{strategy_a,strategy_b,strategy_c}.json` — Exclusion configurations
- `/app/truth_set.json` — Variant truth labels
- `/app/pipeline.py` — Pipeline: `python3 /app/pipeline.py <config.json> <output_dir>`

## Required outputs

### `/app/evaluation.json`

```json
{
  "strategy_a": {
    "sensitivity": "<float, 4 dp>",
    "specificity": "<float, 4 dp>",
    "coverage_fraction": "<float, 4 dp>",
    "composite_score": "<float, 4 dp>",
    "retained_variants": "<int>",
    "excluded_variants": "<int>"
  },
  "strategy_b": { "..." },
  "strategy_c": { "..." },
  "ranking": ["<best>", "<middle>", "<worst>"],
  "best_strategy": "<name>"
}
```

### `/app/step_impact.json`

Per-exclusion-step variant impact analysis for the best strategy:

```json
{
  "analyzed_strategy": "<name>",
  "steps": [
    {
      "step_name": "<name>",
      "validated_true_lost": "<int>",
      "validated_false_excluded": "<int>",
      "true_positions_lost": [<positions>],
      "false_positions_excluded": [<positions>]
    }
  ],
  "weakest_step": "<step name>",
  "weakest_step_reason": "<explanation>"
}
```

### `/app/optimized_config.json`

An exclusion configuration (same JSON schema as the strategy files) that achieves perfect sensitivity and specificity.

### `/app/output/`

Pipeline outputs from the optimized configuration: `benchmark_regions.bed`, `exclusion_stats.tsv`, `benchmark_variants.vcf`, `variant_summary.json`.