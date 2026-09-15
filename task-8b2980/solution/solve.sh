#!/bin/bash

# Discover strategy configurations from the constraints database
echo "=== Strategy configurations ==="
sqlite3 /app/constraints.db "SELECT name, ranks, layers, batches, time_limit, memory_limit FROM strategies" -header -column

echo ""
echo "=== Communication costs ==="
sqlite3 /app/constraints.db "SELECT * FROM communication_costs" -header -column

# Copy the solution strategies implementation
cp /solution/strategies.py /app/strategies.py

# Validate all strategies using the dtrain CLI
echo ""
echo "=== Running validations ==="
cd /app
./dtrain run fsdp | jq .
./dtrain run gpipe | jq .
./dtrain run pipeline_fsdp | jq .

# Show profile summaries
echo ""
echo "=== Profile summaries ==="
for s in fsdp gpipe pipeline_fsdp; do
    ./dtrain profile "$s" | jq "{strategy: .strategy, ranks: [.per_rank[] | {rank: .rank, time: .total_time, peak_memory: .peak_memory}]}"
done
