# MTRAG Evaluation Pipeline Specification


## Overview

Build a Python CLI tool at `/app/mtrag_eval.py` that evaluates multi-turn RAG systems using the MTRAG benchmark format. The tool must support four subcommands: `validate`, `evaluate`, `rank`, and `compare`.

## Data Format

### Input File (`input.jsonl`)
Each line is a JSON object with:
- `task_id` (string): Unique identifier in format `{conversation_id}_t{turn_number}`
- `conversation_id` (string): Conversation identifier
- `Collection` (string): Collection identifier in format `mt-rag-{domain}-elser-512-100`
- `input` (array): List of conversation turns, each with `speaker` ("user" or "agent") and `text`
- `targets` (array): List of reference responses, each with `text`

### Prediction Files (`*.jsonl`)
Each line is a JSON object with:
- `task_id` (string): Must match an input task_id
- `conversation_id` (string): Conversation identifier
- `Collection` (string): Collection identifier
- `input` (array): Conversation turns (same format as input)
- `contexts` (array): Retrieved passages, each with:
  - `document_id` (string): Document identifier
  - `text` (string): Passage text
  - `score` (number): Retrieval score (higher = more relevant)
- `predictions` (array): Generated responses, each with `text`

### Qrels Files (`*.tsv`)
Tab-separated files with header `query_id\tcorpus_id\tscore`:
- `query_id`: Matches task_id from input/prediction files
- `corpus_id`: Matches document_id from contexts
- `score`: Integer relevance grade (0 = not relevant, 1 = relevant, 2 = highly relevant)

### Collection-to-Domain Mapping
The collection identifier format is `mt-rag-{domain}-elser-512-100`. Extract the domain name to find the corresponding qrels file `{domain}.tsv` in the qrels directory.

## CLI Interface

### 1. Format Validation

```
python3 /app/mtrag_eval.py validate \
  --input <input.jsonl> \
  --predictions <predictions.jsonl> \
  --mode <retrieval_taska|generation_taskb|rag_taskc>
```

**Exit code**: 0 if valid, non-zero if errors found.

**Validation rules by mode:**

- `retrieval_taska`: Each prediction must have `task_id` (string), `Collection` (string), `contexts` (array). Each context must have `document_id` (string) and `score` (numeric).

- `generation_taskb`: Each prediction must have `task_id` (string), `input` (array), `contexts` (array), `predictions` (array). Each prediction entry must have `text` (string).

- `rag_taskc`: Each prediction must have `task_id` (string), `Collection` (string), `input` (array), `contexts` (array), `predictions` (array). Context and prediction validation as above.

**Cross-file checks**: All task_ids in the input file must appear in the prediction file, and vice versa.

### 2. Evaluation

```
python3 /app/mtrag_eval.py evaluate \
  --input <input.jsonl> \
  --predictions <predictions.jsonl> \
  --qrels-dir <directory> \
  --output <output.json>
```

Computes retrieval and generation metrics and writes results as JSON.

**Retrieval metrics**:
- Compute nDCG@k and Recall@k for k in {1, 3, 5} using graded relevance judgments from qrels
- Group predictions by collection domain
- For each domain, load corresponding qrels file and evaluate using standard IR evaluation methodology for graded relevance
- Compute weighted cross-collection averages (weighted by query count per collection)

**Generation metrics**:
- Compute ROUGE-L F1 (without stemming) for each task by comparing prediction text against reference target text from the input file
- Join on task_id
- Report per-task and average scores

**Per-query metrics**:
- For each query (task_id), report individual nDCG@5, Recall@5, and ROUGE-L F1 scores
- These per-query scores are required for downstream statistical significance testing via the `compare` subcommand

**Overall score**:
- Harmonic mean of (weighted nDCG@5, weighted Recall@5, average ROUGE-L F1)
- If any value is 0, harmonic mean is 0

**Output JSON format:**
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
    "per_task": {"<task_id>": float, ...}
  },
  "per_query": {
    "<task_id>": {
      "nDCG@5": float,
      "Recall@5": float,
      "ROUGE-L_F1": float
    },
    ...
  },
  "overall": {
    "harmonic_mean": float
  }
}
```

All float values should be rounded to 5 decimal places.

### 3. System Ranking

```
python3 /app/mtrag_eval.py rank \
  --results-dir <directory> \
  --output <output.csv>
```

Reads all `*.json` result files from `results-dir`. Each file's stem is the system name.

**Output CSV format** (sorted by harmonic_mean descending):
```
rank,system,nDCG@5,Recall@5,ROUGE-L_F1,harmonic_mean
1,system_a,0.xxxxx,0.xxxxx,0.xxxxx,0.xxxxx
2,system_b,0.xxxxx,0.xxxxx,0.xxxxx,0.xxxxx
```

### 4. Statistical Comparison

```
python3 /app/mtrag_eval.py compare \
  --result-a <result_a.json> \
  --result-b <result_b.json> \
  --output <comparison.json> \
  [--seed <int>]              # default: 42
  [--num-permutations <int>]  # default: 10000
```

Performs pairwise statistical significance testing between two systems using a paired permutation test on per-query scores. Uses the `per_query` section from each system's evaluation result JSON.

For each metric (nDCG@5, Recall@5, ROUGE-L_F1), the test determines whether the observed mean difference between systems is statistically significant under a two-tailed null hypothesis. The `--seed` parameter ensures reproducibility.

**Output JSON format:**
```json
{
  "system_a": "<filename stem of result-a>",
  "system_b": "<filename stem of result-b>",
  "num_queries": int,
  "seed": int,
  "num_permutations": int,
  "metrics": {
    "nDCG@5": {
      "mean_a": float,
      "mean_b": float,
      "delta": float,
      "p_value": float,
      "significant": bool
    },
    "Recall@5": { ... },
    "ROUGE-L_F1": { ... }
  }
}
```

Where `delta` = `mean_a` - `mean_b`, and `significant` is true if `p_value < 0.05`. All float values rounded to 5 decimal places.

## Data

All data is at `/app/data/`:
- `/app/data/input.jsonl` — 9 multi-turn RAG tasks across 2 collections
- `/app/data/qrels/alpha.tsv` — Relevance judgments for alpha collection (graded: 0/1/2)
- `/app/data/qrels/beta.tsv` — Relevance judgments for beta collection (graded: 0/1/2)
- `/app/data/predictions/system_a.jsonl` — High-quality system predictions
- `/app/data/predictions/system_b.jsonl` — Medium-quality system predictions
- `/app/data/predictions/system_c.jsonl` — Intentionally malformed predictions for validation testing
