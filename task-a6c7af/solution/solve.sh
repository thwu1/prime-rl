#!/bin/bash

cp /solution/thermoengine.py /app/thermoengine.py
cp /solution/pipeline.sh /app/pipeline.sh
chmod +x /app/pipeline.sh
cd /app
bash /app/pipeline.sh
