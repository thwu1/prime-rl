#!/bin/bash

cp /solution/encoder.py /app/encoder.py
cd /app
python3 /app/encoder.py

# Verify message integrity with compiled validator
/app/msgcheck -v /app/messages.txt
