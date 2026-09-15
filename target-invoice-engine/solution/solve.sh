#!/bin/bash

cp /solution/run_pipeline.sh /app/run_pipeline.sh
cp /solution/billing_engine.py /app/billing_engine.py
chmod +x /app/run_pipeline.sh
cd /app
/app/run_pipeline.sh
