#!/usr/bin/env bash

set -e

cp /solution/backfill.py /app/backfill.py

python3 /app/backfill.py /app/manifest.json /app/vintages/ /app/output/repo/

echo "Solution complete."
