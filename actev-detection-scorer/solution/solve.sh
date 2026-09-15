#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

cp /solution/scorer.py /app/scorer.py

python3 /app/scorer.py --config /app/eval_config.toml --output-dir /app/output
