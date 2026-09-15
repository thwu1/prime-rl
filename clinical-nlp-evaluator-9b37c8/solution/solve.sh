#!/bin/bash

pip3 install scipy==1.14.1 numpy==2.1.3 -q

mkdir -p /app/clinical_eval
cp /solution/evaluate.py /app/clinical_eval/evaluate.py
