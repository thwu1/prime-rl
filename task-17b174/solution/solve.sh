#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

cp /solution/scorer_solution.py /app/scorer.py

python3 /app/scorer.py \
    --reference /app/data/reference.json \
    --system-output /app/data/system_output.json \
    --activity-index /app/data/activity_index.json \
    --file-index /app/data/file_index.json \
    --scoring-parameters /app/data/scoring_parameters.json \
    --output-dir /app/output
