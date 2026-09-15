An information retrieval evaluation pipeline at `/app/` benchmarks four retrieval models (`bm25`, `dense`, `sparse`, `reranker`) across a graded-relevance dataset spanning three domains (`biology`, `economics`, `coding`). The pipeline currently fails to produce correct evaluation results, and its score-fusion optimization module is incomplete.

Critically assess the entire pipeline for correctness — every stage from data ingestion through metric computation may contain flaws. Fix all issues you identify, design and implement the fusion optimization, and generate accurate output.

Run the corrected pipeline to produce `/app/results.json`.

## Environment

- `/app/data/qrels.txt` — TREC relevance judgments (graded 0–3)
- `/app/data/runs/{bm25,dense,sparse,reranker}.trec` — TREC retrieval runs
- `/app/data/queries.jsonl` — Query metadata (`id`, `domain`, `query`)
- `/app/config.json` — Pipeline configuration
- `/app/src/` — `evaluate.py`, `trec_utils.py`, `fusion.py`, `metrics.py`, `utils.py`

## Output Schema

`/app/results.json`:

```json
{
  "baseline_metrics": {
    "<model>": {
      "overall": {"nDCG@5": float, "nDCG@10": float, "MAP@10": float, "MRR": float},
      "per_domain": {
        "<domain>": {"nDCG@5": float, "nDCG@10": float, "MAP@10": float, "MRR": float}
      }
    }
  },
  "fusion_optimization": {
    "<domain>": {
      "best_method": "<key with highest nDCG@10>",
      "best_ndcg10": float,
      "all_methods": {
        "rrf_k10": float, "rrf_k30": float, "rrf_k60": float, "rrf_k100": float,
        "combsum": float, "combmnz": float, "weighted_combsum": float
      }
    }
  },
  "optimized_fusion": {
    "overall": {"nDCG@5": float, "nDCG@10": float, "MAP@10": float, "MRR": float},
    "per_domain": {
      "<domain>": {"nDCG@5": float, "nDCG@10": float, "MAP@10": float, "MRR": float}
    }
  }
}
```

- `<model>` ∈ {`bm25`, `dense`, `sparse`, `reranker`}; `<domain>` ∈ {`biology`, `economics`, `coding`}
- All floats are mean values across the relevant query set
- `optimized_fusion` applies each domain's best fusion method to that domain's queries, combines the per-domain fused results into a single set, then evaluates with the full metric suite