#!/bin/bash

cp /solution/decode_solution.py /app/decode.py
cp /solution/audit_solution.py /app/audit.py
cd /app && python3 decode.py && python3 audit.py
