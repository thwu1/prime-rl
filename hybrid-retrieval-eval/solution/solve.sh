#!/bin/bash

# Install torch CPU-only from dedicated index
pip3 install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu -q

# Install remaining dependencies from PyPI
pip3 install sentence-transformers==2.7.0 scikit-learn==1.5.2 numpy==2.1.3 -q

python3 /solution/retrieval.py
