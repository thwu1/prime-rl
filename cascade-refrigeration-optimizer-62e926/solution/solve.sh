#!/bin/bash


pip3 install CoolProp==6.6.0 scipy==1.14.1 -q

cd /app
python3 /solution/cascade_audit.py
