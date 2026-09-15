#!/bin/bash

cd /app
mkdir -p /app/rules
cp /solution/rules/*.yar /app/rules/
cp /solution/auditor.py /app/auditor.py
python3 /app/auditor.py
