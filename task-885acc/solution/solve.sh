#!/bin/bash

pip3 install numpy==1.26.4 -q
cd /app/tools && make -s
python3 /solution/slam_optimizer.py
