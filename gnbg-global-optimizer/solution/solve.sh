#!/bin/bash


pip3 install cma==3.4.0 scipy==1.14.1 -q

cp /solution/optimizer_impl.py /app/optimizer.py

echo "Optimizer installed at /app/optimizer.py"
