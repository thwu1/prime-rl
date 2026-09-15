# Result Evaluation

## TREC Run Format

Query results must be output in the standard TREC run format, one line per result:

    <query_id> Q0 <document_id> <rank> <score> <run_tag>

Fields are whitespace-separated. `<document_id>` must use the external
document identifier from the metadata store.

## Evaluation Tool

The `trec_eval` source is available at `/app/tools/trec_eval/`. It is the
standard NIST evaluation tool for information retrieval experiments.

## Relevance Judgments

Relevance judgments are provided at `/app/qrels/eval.qrels` in standard format:

    <query_id> 0 <document_id> <relevance>

Relevance levels: 0 (not relevant), 1 (marginally relevant),
2 (relevant), 3 (highly relevant).
