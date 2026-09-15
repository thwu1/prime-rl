#!/usr/bin/env bash

cp /solution/resolve_config.sh /app/resolve_config.sh
cp /solution/massim_engine.py /app/massim_engine.py
cp /solution/run_pipeline.py /app/run_pipeline.py
chmod +x /app/resolve_config.sh
bash /app/resolve_config.sh
python3 /app/run_pipeline.py
