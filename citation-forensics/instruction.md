Build a citation reliability evaluation pipeline for U.S. legal language model outputs that integrates heterogeneous data sources stored across multiple formats and computes multi-dimensional quality metrics with parallel citation resolution.

Evaluation data and configuration reside in `/app/data/`. The configuration file (`eval_config.yaml`) references all data sources, which are stored in purpose-specific formats requiring different parsing approaches. Discover each source, determine its format, and integrate all data before computing metrics.

The SQLite database stores model responses with reference citations as embedded JSON arrays and includes a parallel citation cross-reference table mapping equivalent citations across different reporter systems. Court hierarchy data and error detection records use separate format-specific files. A supplementary JSONL file provides additional model responses that must be merged with the primary data.

The methodology document (`/app/data/methodology.md`) describes the evaluation framework. It covers citation extraction with Bluebook conventions, parallel citation equivalence, retrieval quality metrics, jurisdiction-weighted scoring, misleading answer rate, fabrication analysis, and citation error detection with severity weighting.

Produce `/app/output/results.json`:

```json
{
  "retrieval_f1": {"<model>": {"<category>": <float>, "overall": <float>, "weighted_overall": <float>}},
  "mar": {"threshold": <int>, "<model>": <float_or_null>, "overall": <float>},
  "normalized_overall": {"<model>": <float>},
  "fabrication_rate": {"<model>": <float>},
  "error_detection": {
    "detection_accuracy": <float>,
    "classification_accuracy": <float>,
    "severity_weighted_accuracy": <float>,
    "type_counts": {"volume": <int>, "page": <int>, "reporter": <int>}
  },
  "record_details": [{"id": "<str>", "model": "<str>", "f1_score": <float>, "is_concrete": <bool>}]
}
```

Citation extraction must handle the full range of Bluebook reporter conventions including federal, regional, state-name, and compound reporters. Scores on the 0-100 scale where applicable.