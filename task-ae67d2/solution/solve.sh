#!/bin/bash

pip3 install pymatching==2.2.1 ldpc==2.4.1 -q

cp /solution/dem_to_matrices.py /app/dem_to_matrices.py
cp /solution/decoder.py /app/decoder.py

python3 /solution/verify.py
