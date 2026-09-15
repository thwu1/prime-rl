#!/bin/bash

set -e

pip3 install PyYAML==6.0.2 -q

mkdir -p /app/orchestrator

cp /solution/models.py /app/orchestrator/models.py
cp /solution/registry.py /app/orchestrator/registry.py
cp /solution/engine.py /app/orchestrator/engine.py
cp /solution/init_module.py /app/orchestrator/__init__.py
