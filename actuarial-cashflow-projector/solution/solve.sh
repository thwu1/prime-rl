#!/bin/bash

pip3 install numpy==2.1.3 pandas==2.2.3 pyarrow==17.0.0 -q

cp /solution/projector.py /app/projector.py
cd /app
python3 /app/projector.py
