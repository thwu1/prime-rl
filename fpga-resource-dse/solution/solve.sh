#!/bin/bash

cd /app

# Stage 1: Flatten nested synthesis data to JSONL using jq
jq -c 'to_entries[] | .key as $model | .value | to_entries[] | .key as $cat | .value[] | .module as $mod | .solutions | to_entries[] | .key as $idx | .value | select(."resource usage" != null and (."resource usage" | has("optimized"))) | {model: $model, category: $cat, module: $mod, solution_index: $idx, pass_status: .pass, lut: ."resource usage".optimized.LUT, ff: ."resource usage".optimized.FF, dsp: ."resource usage".optimized.DSP, bram: ."resource usage".optimized.BRAM, io: ."resource usage".optimized.IO}' /app/solutions_data.json > /app/validated_solutions.jsonl

# Stage 2: Run analysis pipeline (creates SQLite DB and JSON report)
python3 /solution/pipeline.py
