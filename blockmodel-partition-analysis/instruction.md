A network analysis project at `/app/` evaluates candidate community detection results on a synthetic directed graph generated from a degree-corrected stochastic blockmodel (DC-SBM). The analysis pipeline at `/app/pipeline/` runs end-to-end without crashing but produces incorrect results. Investigate the pipeline code, identify and fix all bugs, and produce a correct `/app/results.json`.

The project contains a directed weighted graph at `/app/data/network.tsv` (tab-separated: source, destination, weight; 1-indexed nodes), a ground truth partition at `/app/data/ground_truth.tsv` (tab-separated: node, block; 1-indexed), and six candidate partitions at `/app/data/detections/result_{A,B,C,D,E,F}.tsv` in the same format. Project documentation is at `/app/pipeline/notes.md`.

## Output specification

`/app/results.json` must be a JSON file with this exact schema:

```json
{
  "description_lengths": {
    "truth": <float>,
    "A": <float>, "B": <float>, "C": <float>,
    "D": <float>, "E": <float>, "F": <float>
  },
  "best_partition": "<letter A-F with lowest description length>",
  "ranking": ["<letter>", "...six candidates sorted by description length ascending"],
  "comparison_metrics": {
    "A": {"accuracy": <float>, "ari": <float>, "nmi": <float>},
    "B": {"accuracy": <float>, "ari": <float>, "nmi": <float>},
    "C": {"accuracy": <float>, "ari": <float>, "nmi": <float>},
    "D": {"accuracy": <float>, "ari": <float>, "nmi": <float>},
    "E": {"accuracy": <float>, "ari": <float>, "nmi": <float>},
    "F": {"accuracy": <float>, "ari": <float>, "nmi": <float>}
  }
}
```

## Requirements

- All description lengths must be correct within 0.1% relative error.
- All comparison metrics (accuracy, ARI, NMI) must be correct within 0.005 absolute error.
- The `best_partition` and `ranking` must be consistent with the computed description lengths.
- The results must be internally coherent: near-perfect partitions should score higher than random ones on all metrics, and single-block partitions should have near-zero NMI and ARI.