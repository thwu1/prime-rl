#!/bin/bash

pip3 install pandas==2.2.3 numpy==2.1.3 scipy==1.14.1 -q 2>&1

cd /app
python3 /solution/compute.py
