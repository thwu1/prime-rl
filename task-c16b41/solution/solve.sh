#!/bin/bash

set -e

pip3 install pyyaml==6.0.2 -q

cp /solution/validator_impl.py /app/validator.py
cp /solution/planner_impl.py /app/planner.py
cp /solution/pipeline_impl.sh /app/pipeline.sh

chmod +x /app/validator.py /app/planner.py /app/pipeline.sh
