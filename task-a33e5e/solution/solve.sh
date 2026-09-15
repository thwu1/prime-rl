#!/usr/bin/env bash

# Copy solution implementation into place
cp /solution/star_tree_impl.py /app/star_tree.py

# Verify the implementation works with a computational sanity check
python3 -c "
import sys, csv, json
sys.path.insert(0, '/app')
from star_tree import StarTreeBuilder, StarTreeQueryEngine, merge_star_trees, STAR

with open('/app/config.json') as f:
    config = json.load(f)

def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))

data_a = load('/app/data/sales_data_segment_a.csv')
data_b = load('/app/data/sales_data_segment_b.csv')

builder_a = StarTreeBuilder(config)
root_a = builder_a.build(data_a)
engine_a = StarTreeQueryEngine(root_a, config)

builder_b = StarTreeBuilder(config)
root_b = builder_b.build(data_b)

# Verify single tree total revenue matches DNA
total_a = engine_a.query({}, 'revenue', 'SUM')
assert abs(total_a - 4358853.35) / 4358853.35 < 1e-9, f'Revenue SUM mismatch: {total_a}'

# Verify group-by
gb = engine_a.group_by_query({}, 'region', 'revenue', 'SUM')
assert len(gb) == 5, f'Expected 5 regions, got {len(gb)}'

# Merge and verify
merged = merge_star_trees(root_a, root_b, config)
engine_m = StarTreeQueryEngine(merged, config)
total_m = engine_m.query({}, 'revenue', 'SUM')
assert abs(total_m - 8740891.04) / 8740891.04 < 1e-9, f'Merged SUM mismatch: {total_m}'

# Verify AVG correctness through merge
avg_m = engine_m.query({'region': 'EU'}, 'discount', 'AVG')
eu_vals = [float(r['discount']) for r in data_a + data_b if r['region'] == 'EU']
bf_avg = sum(eu_vals) / len(eu_vals)
assert abs(avg_m - bf_avg) / bf_avg < 1e-6, f'Merged AVG mismatch: {avg_m} vs {bf_avg}'

print(f'Segment A: {len(data_a)} records, revenue SUM = {total_a:.2f}')
print(f'Merged: {merged.document_count} records, revenue SUM = {total_m:.2f}')
print(f'EU discount AVG = {avg_m:.6f} (brute-force = {bf_avg:.6f})')
print('All sanity checks passed.')
"
