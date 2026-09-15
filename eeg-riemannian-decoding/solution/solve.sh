#!/bin/bash

pip3 install numpy==2.1.3 scipy==1.14.1 scikit-learn==1.5.2 -q

# Ensure synthetic EEG data exists (regenerate if Docker build artifacts were cleared)
if [ ! -f /app/data/metadata.npz ]; then
    python3 /opt/generate_data.py
fi

cp /solution/pipeline.py /app/pipeline.py
cd /app
python3 pipeline.py
