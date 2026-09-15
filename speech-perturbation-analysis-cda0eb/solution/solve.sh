#!/bin/bash


pip3 install scipy==1.14.1 numpy==2.1.3 -q

cp /solution/phonation.py /app/phonation.py
cp /solution/prosody.py /app/prosody.py
cp /solution/extract.py /app/extract.py
cp /solution/preprocess.sh /app/preprocess.sh
chmod +x /app/preprocess.sh
