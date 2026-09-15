#!/bin/bash

cp /solution/extract.sql /app/pipeline/extract.sql
cp /solution/compute_metrics.py /app/pipeline/compute_metrics.py
cp /solution/rank_and_validate.jq /app/pipeline/rank_and_validate.jq

make -C /app clean
make -C /app all
