#!/bin/bash

pip3 install pytest==8.3.4 -q

# Copy autorepair tool into place
cp /solution/autorepair.py /app/autorepair.py

# Create output directory
mkdir -p /app/output

# Run repair on all four subjects
python3 /app/autorepair.py /app/subjects/sorting_utils
python3 /app/autorepair.py /app/subjects/graph_utils
python3 /app/autorepair.py /app/subjects/string_utils
python3 /app/autorepair.py /app/subjects/cache_utils
