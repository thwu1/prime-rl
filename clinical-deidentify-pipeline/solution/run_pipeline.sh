#!/bin/bash
mkdir -p /app/output
python3 /app/pipeline.py /app/corpus/doc_001.txt doc_001 /app/output
python3 /app/pipeline.py /app/corpus/doc_002.txt doc_002 /app/output
python3 /app/pipeline.py /app/corpus/doc_003.txt doc_003 /app/output
