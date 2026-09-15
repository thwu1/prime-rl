#!/bin/bash

# Deploy the translator to /app/ and run it
cp /solution/translator.py /app/translate.py
cd /app
python3 /app/translate.py
