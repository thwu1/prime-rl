#!/bin/bash

pip3 install xxhash==3.5.0 -q

cp /solution/fixed_vindex.py /app/vindex.py
cp /solution/fixed_reshard.py /app/reshard.py
cp /solution/fixed_vdiff.py /app/vdiff.py
cp /solution/fixed_jobs.py /app/jobs.py
