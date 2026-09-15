#!/bin/bash

cd /app
python3 /solution/fix_pipeline.py
python3 -m pipeline.main
