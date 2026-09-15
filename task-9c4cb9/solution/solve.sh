#!/bin/bash

cp /solution/pipeline.py /app/pipeline.py
python3 /app/pipeline.py /app/stations /app/tracks.db /app/report.json
