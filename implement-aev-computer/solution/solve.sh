#!/bin/bash

pip3 install numpy==1.26.4 h5py==3.11.0 -q
cp /solution/pipeline_impl.py /app/aev_pipeline.py
python3 /app/aev_pipeline.py
