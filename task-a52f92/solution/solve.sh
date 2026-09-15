#!/bin/bash

# Deploy the override module and patch the runner
cp /solution/slt_override.py /app/slt_override.py
python3 /solution/patch_runner.py
