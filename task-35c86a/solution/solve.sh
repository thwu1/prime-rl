#!/bin/bash

cp /solution/noc_pipeline.py /app/noc_pipeline.py

python3 /app/noc_pipeline.py --config /app/wormhole_grid.json --harvested-rows "" --output /app/output.json
