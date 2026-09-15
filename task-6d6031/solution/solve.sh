#!/bin/bash

pip3 install pyarrow==17.0.0 duckdb==1.1.3 pandas==2.2.3 -q

python3 /solution/build_cache.py
python3 /solution/run_queries.py
