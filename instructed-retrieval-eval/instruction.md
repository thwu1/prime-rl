`/app/` contains a multi-domain information retrieval evaluation benchmark. `/app/data/` has heterogeneous retrieval task data (TREC-format runs, JSONL corpora, graded and binary qrels across three domains). `/app/config.json` defines the full evaluation methodology — including required evaluation backends, metric specifications, statistical tests, rank correlation analysis, and the output schema.

`/app/evaluate.py` is a draft evaluation script. It is incomplete and produces incorrect results.

Produce `/app/results.json` conforming exactly to the schema and methodology specified in `/app/config.json`.