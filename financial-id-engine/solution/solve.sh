#!/bin/bash

# No additional pip packages needed — pure Python stdlib + sqlite3
cp /solution/fid_engine.py /app/fid_engine.py
python3 /app/fid_engine.py /app/data/batch.json /app/data/iban.dat /app/output/identifiers.db /app/output/report.json
