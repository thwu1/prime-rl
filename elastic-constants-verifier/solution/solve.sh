#!/bin/bash


pip3 install numpy==1.26.4 scipy==1.13.1 numdifftools==0.9.41 -q

cp /solution/elastic_verifier.py /app/elastic_verifier.py
cd /app
python3 elastic_verifier.py
