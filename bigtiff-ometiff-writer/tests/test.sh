#!/bin/bash

pip3 install pytest==8.3.5 numpy==2.1.3 tifffile==2024.9.20 imagecodecs==2024.9.22 -q

# Ensure the input dataset exists (restore from backup if /app was cleared)
if [ ! -f /app/dataset.npy ]; then
    if [ -f /opt/dataset_backup.npy ]; then
        cp /opt/dataset_backup.npy /app/dataset.npy
    elif [ -f /opt/generate_data.py ]; then
        python3 /opt/generate_data.py
    fi
fi

# Run the builder if output doesn't exist yet
if [ -f /app/lzw_tiff_writer.py ] && [ ! -f /app/output.tif ]; then
    python3 /app/lzw_tiff_writer.py /app/dataset.npy /app/output.tif
fi

# Run pytest
pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
