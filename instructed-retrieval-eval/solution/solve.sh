#!/bin/bash

pip3 install pytrec-eval-terrier==0.5.6 scipy==1.14.1 numpy==2.1.3 -q
cd /app
python3 /solution/ir_eval.py
