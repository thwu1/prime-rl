#!/bin/bash

pip3 install numpy==2.1.3 -q

# Deploy the inference engine
cp /solution/inference_impl.py /app/inference.py
