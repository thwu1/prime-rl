#!/bin/bash

pip3 install numpy==2.1.3 -q

cp /solution/beam_pipeline_impl.py /app/beam_pipeline.py
cd /app
python3 /app/beam_pipeline.py
