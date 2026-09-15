#!/bin/bash

# Deploy the scorer implementation
cp /solution/scorer_impl.py /app/scorer.py

# Verify with sample objects
echo "Verifying scorer with sample objects..."
python3 /app/scorer.py /app/objects/sample_basic.o /app/objects/sample_renamed.o
echo ""
python3 /app/scorer.py /app/objects/sample_basic.o /app/objects/sample_different.o
echo ""
python3 /app/scorer.py /app/objects/sample_basic.o /app/objects/sample_longer.o
echo ""
echo "Scorer deployed successfully at /app/scorer.py"
