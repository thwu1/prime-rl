# Partition Evaluation Pipeline

Evaluates candidate community detection results for a DC-SBM network.

## Data Layout

- `data/network.tsv`: directed graph, tab-separated (source dest weight), 1-indexed nodes
- `data/ground_truth.tsv`: true community assignments (node block), 1-indexed
- `data/detections/result_{A..F}.tsv`: candidate partitions from different detection methods

## How to Run

    cd /app && python3 pipeline/analyze.py

## Expected Output: `/app/results.json`

    {
      "description_lengths": {"truth": <float>, "A": <float>, ..., "F": <float>},
      "best_partition": "<letter>",
      "ranking": ["<letter>", ...],
      "comparison_metrics": {
        "A": {"accuracy": <float>, "ari": <float>, "nmi": <float>},
        ...
      }
    }

- `best_partition`: candidate (A-F) with lowest description length
- `ranking`: candidates sorted by description length ascending
- `accuracy`: fraction of nodes correctly classified under optimal label alignment
- `nmi`: normalized mutual information with arithmetic mean normalization, i.e. NMI = 2*MI / (H(X) + H(Y))

## Status

Pipeline runs end-to-end but results haven't been validated against a reference
implementation. The description length ranking looks suspicious -- partitions
known to be near-truth don't rank as expected.
