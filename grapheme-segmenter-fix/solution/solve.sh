#!/usr/bin/env bash

cd /app

# Deploy the complete sentence segmenter implementation
python3 /solution/implement_sentence.py

# Verify full conformance
python3 /app/validate.py
