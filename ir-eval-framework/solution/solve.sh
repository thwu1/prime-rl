#!/bin/bash

pip3 install scipy==1.14.1 -q

cp /solution/pipeline_fixed.py /app/pipeline.py

python3 /app/pipeline.py --qrels /app/data/qrels.tsv --runs /app/data/runs/ --output /app/results.json
