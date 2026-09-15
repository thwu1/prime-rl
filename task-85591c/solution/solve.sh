#!/bin/bash

pip3 install edn_format==0.7.5 -q

cp /solution/solver.py /app/auditor
chmod +x /app/auditor
