#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 scikit-learn==1.5.2 -q

# Generate data
python3 /app/generate_data.py

# Copy reference solution as calibrate.py
cp /solution/solution_pipeline.py /app/calibrate.py

# Run the pipeline
python3 /app/calibrate.py
