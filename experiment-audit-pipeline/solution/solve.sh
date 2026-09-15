#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 h5py==3.11.0 pyarrow==17.0.0 duckdb==1.1.0 -q

cp /solution/audit_tool.py /app/audit.py
python3 /app/audit.py
