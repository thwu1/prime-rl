#!/bin/bash

# Copy reference implementation to /app/
cp /solution/reference_core.py /app/pcfg_core.py
cp /solution/reference_pipeline.sh /app/pcfg_pipeline.sh
chmod +x /app/pcfg_pipeline.sh

# Run the pipeline to verify correctness
/app/pcfg_pipeline.sh --grammar /app/grammar.gr --corpus /app/corpus.txt --iterations 20 > /dev/null 2>&1

if [ $? -ne 0 ]; then
    echo "ERROR: Pipeline failed"
    exit 1
fi

echo "Solution installed successfully"
