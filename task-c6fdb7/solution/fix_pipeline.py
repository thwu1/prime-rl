#!/usr/bin/env python3
"""Fix all bugs in the search evaluation pipeline."""

# Bug 1: config.yaml references wrong filename for dense system
with open('/app/config.yaml') as f:
    config_text = f.read()
config_text = config_text.replace('dense_results.json', 'dense.json')
with open('/app/config.yaml', 'w') as f:
    f.write(config_text)

# Bug 2-4: evaluate.py has three bugs
with open('/app/pipeline/evaluate.py') as f:
    eval_text = f.read()

# Bug 2: nDCG uses natural log instead of log base 2
eval_text = eval_text.replace('math.log(i + 2)', 'math.log2(i + 2)')

# Bug 3: MAP@k divides by total_relevant instead of min(total_relevant, k)
eval_text = eval_text.replace(
    'return sum_prec / total_relevant',
    'return sum_prec / min(total_relevant, k)'
)

# Bug 4: SQL query doesn't aggregate across annotators (should take MAX)
eval_text = eval_text.replace(
    'SELECT query_id, doc_id, relevance FROM judgments',
    'SELECT query_id, doc_id, MAX(relevance) as relevance FROM judgments GROUP BY query_id, doc_id'
)

with open('/app/pipeline/evaluate.py', 'w') as f:
    f.write(eval_text)

# Bug 5: fusion.py RRF uses 0-based ranking instead of 1-based
with open('/app/pipeline/fusion.py') as f:
    fusion_text = f.read()

fusion_text = fusion_text.replace(
    'enumerate(sys_runs[qid])',
    'enumerate(sys_runs[qid], 1)'
)

with open('/app/pipeline/fusion.py', 'w') as f:
    f.write(fusion_text)

print("All pipeline bugs fixed.")
