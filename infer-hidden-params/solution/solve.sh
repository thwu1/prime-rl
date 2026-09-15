#!/usr/bin/env bash

pip3 install numpy==2.1.3 -q 2>/dev/null || true

cp /solution/infer_params.py /app/infer_params.py
python3 /app/infer_params.py
