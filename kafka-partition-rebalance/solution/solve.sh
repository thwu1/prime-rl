#!/bin/bash

pip3 install pyyaml==6.0.2 -q

cd /app
python3 /solution/solver.py

# Validate the plan using kafkactl
kafkactl validate /app/reassignment_plan.json -o /app/validation_report.json
