#!/bin/bash

pip3 install pandas==2.2.3 scikit-learn==1.6.1 numpy==2.1.3 -q

cp /solution/pipeline.py /app/pipeline.py
cd /app
python3 pipeline.py
