#!/bin/bash

pip3 install pyarrow==18.1.0 pandas==2.2.3 numpy==2.1.3 -q

cp /solution/compact.py /app/compact.py
cd /app
python3 compact.py
