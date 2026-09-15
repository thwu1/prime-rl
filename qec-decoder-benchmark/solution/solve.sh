#!/bin/bash

python3 -m pip install numpy==2.2.6 stim==1.15.0 tesseract-decoder==0.1.1.dev20260526203925 -q

cp /solution/qec_pipeline.py /app/qec_pipeline.py
cd /app && python3 qec_pipeline.py
