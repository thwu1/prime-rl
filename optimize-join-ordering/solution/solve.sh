#!/bin/bash

cp /solution/optimizer_solution.py /app/optimizer.py

python3 -c "
import sys, json
sys.path.insert(0, '/app')
from optimizer import optimize

with open('/opt/task_data/stats.json') as f:
    stats = json.load(f)
with open('/opt/task_data/queries.json') as f:
    queries = json.load(f)['queries']

for q in queries:
    plan = optimize(stats, q)
    print(f\"Query {q['id']}: cost={plan['total_cost']:.2f}, rows={plan['estimated_rows']:.2f}\")
"
