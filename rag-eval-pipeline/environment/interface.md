# MTRAG Evaluation Tool — Interface Contract


## Data

Benchmark data at `/app/data/`:

| Path | Description |
|------|-------------|
| `input.jsonl` | 9 multi-turn RAG tasks across 2 collections |
| `qrels/{domain}.tsv` | Per-collection relevance judgments (graded: 0, 1, 2) |
| `predictions/system_a.jsonl` | High-quality system output |
| `predictions/system_b.jsonl` | Lower-quality system output |
| `predictions/system_c.jsonl` | Malformed output (validation testing) |

### Schemas

**input.jsonl** — one JSON object per line:
```json
{"task_id": "str", "conversation_id": "str", "Collection": "mt-rag-{domain}-elser-512-100", "input": [{"speaker": "user|agent", "text": "str"}], "targets": [{"text": "str"}]}
```

**predictions/*.jsonl** — one JSON object per line:
```json
{"task_id": "str", "conversation_id": "str", "Collection": "str", "input": [...], "contexts": [{"document_id": "str", "text": "str", "score": number}], "predictions": [{"text": "str"}]}
```

**qrels/*.tsv** — TSV with header `query_id	corpus_id	score`

The `Collection` field encodes the domain: `mt-rag-{domain}-elser-512-100` → qrels file `{domain}.tsv`.

## CLI Subcommands

### `validate`
```
python3 /app/mtrag_eval.py validate --input PATH --predictions PATH --mode MODE
```
Modes: `retrieval_taska`, `generation_taskb`, `rag_taskc`

Exit 0 if valid, non-zero on errors. Check JSON structure, required fields per mode, type constraints, and bidirectional task\_id coverage.

| Mode | Required fields |
|------|----------------|
| `retrieval_taska` | task\_id, Collection, contexts (each: document\_id, numeric score) |
| `generation_taskb` | task\_id, input, contexts, predictions (each: text) |
| `rag_taskc` | task\_id, Collection, input, contexts (document\_id + score), predictions (text) |

### `evaluate`
```
python3 /app/mtrag_eval.py evaluate --input PATH --predictions PATH --qrels-dir DIR --output PATH
```

**Output schema:**
```json
{
  "retrieval": {
    "per_collection": {
      "<domain>": {
        "nDCG@1": float, "nDCG@3": float, "nDCG@5": float,
        "Recall@1": float, "Recall@3": float, "Recall@5": float,
        "count": int
      }
    },
    "weighted_average": {
      "nDCG@1": float, "nDCG@3": float, "nDCG@5": float,
      "Recall@1": float, "Recall@3": float, "Recall@5": float
    }
  },
  "generation": {
    "rouge_l_f1": float,
    "per_task": {"<task_id>": float}
  },
  "per_query": {
    "<task_id>": {"nDCG@5": float, "Recall@5": float, "ROUGE-L_F1": float}
  },
  "overall": {
    "harmonic_mean": float
  }
}
```
All floats rounded to 5 decimal places.

### `rank`
```
python3 /app/mtrag_eval.py rank --results-dir DIR --output PATH
```
Reads `*.json` result files; system name = file stem. Output CSV sorted descending by `harmonic_mean`:
```
rank,system,nDCG@5,Recall@5,ROUGE-L_F1,harmonic_mean
```

### `compare`
```
python3 /app/mtrag_eval.py compare --result-a PATH --result-b PATH --output PATH [--seed INT] [--num-permutations INT]
```
Defaults: `seed=42`, `num-permutations=10000`. System names derived from file stems. Operates on `per_query` scores from evaluation results.

**Output schema:**
```json
{
  "system_a": "str", "system_b": "str",
  "num_queries": int, "seed": int, "num_permutations": int,
  "metrics": {
    "nDCG@5": {"mean_a": float, "mean_b": float, "delta": float, "p_value": float, "significant": bool},
    "Recall@5": {"..."},
    "ROUGE-L_F1": {"..."}
  }
}
```
`delta = mean_a - mean_b`. `significant = p_value < 0.05`. All floats rounded to 5 decimal places.
