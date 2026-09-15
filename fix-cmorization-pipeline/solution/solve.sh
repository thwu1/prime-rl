#!/usr/bin/env bash

cd /app
python3 /solution/audit_helper.py
cp /solution/cmorize_correct.py /app/cmorize_final.py
python3 /app/cmorize_final.py
