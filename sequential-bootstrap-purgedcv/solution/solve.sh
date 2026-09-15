#!/bin/bash

pip3 install pandas==2.2.3 numpy==1.26.4 scikit-learn==1.5.2 -q

# Apply corrected pipeline modules
cp /solution/corrected_evaluator.py /app/pipeline/evaluator.py
cp /solution/corrected_sampler.py /app/pipeline/sampler.py
cp /solution/corrected_run.py /app/run.py

# Run the corrected pipeline
cd /app && python3 run.py
