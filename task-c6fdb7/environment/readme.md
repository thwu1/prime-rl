# Search Evaluation Pipeline

Evaluation framework for comparing retrieval system effectiveness and rank fusion strategies.

## Architecture

- `evaluate.py` — Main pipeline: loads data, computes metrics, runs fusion, writes results
- `fusion.py` — Rank fusion implementations (RRF, CombSUM, CombMNZ)
- `config.yaml` — Pipeline configuration (system paths, fusion parameters, significance test settings)

## Data

| File | Format | Description |
|------|--------|-------------|
| `data/corpus.jsonl` | JSONL | Document corpus (50 docs) |
| `data/judgments.db` | SQLite | Multi-annotator graded relevance judgments |
| `data/systems/bm25.run` | TREC run | BM25 lexical retrieval results |
| `data/systems/dense.json.gz` | Gzipped JSON | Dense neural retrieval results |
| `data/systems/sparse.csv` | CSV | Learned sparse retrieval results |

## Judgments Database Schema

The `judgments.db` database has two tables:

### annotators

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | TEXT | Annotator name |
| expertise | TEXT | Expertise level (expert, senior, junior, crowd) |
| weight | REAL | Reliability weight reflecting annotator quality |

### judgments

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment primary key |
| query_id | TEXT | Query identifier |
| doc_id | TEXT | Document identifier |
| annotator_id | INTEGER | Foreign key to annotators table |
| relevance | INTEGER | Relevance grade (0-3 scale) |
| confidence | REAL | Annotator self-reported confidence |
| timestamp | TEXT | Judgment timestamp |

Each (query_id, doc_id) pair has judgments from multiple annotators with varying expertise levels and reliability weights. The annotators table defines each annotator's expertise level and numeric weight.

## Output

The pipeline should produce `results.json` in the working directory. See `schema.json` for the expected output format.
