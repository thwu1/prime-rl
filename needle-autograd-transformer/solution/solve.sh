#!/bin/bash

pip3 install numpy==2.1.3 -q

# Ensure framework directory exists (restore from backup if needed)
mkdir -p /app/needle
if [ ! -f /app/needle/autograd.py ]; then
    cp /opt/needle-src/*.py /app/needle/
fi

cp /solution/ops_complete.py /app/needle/ops.py
cp /solution/nn_complete.py /app/needle/nn.py
