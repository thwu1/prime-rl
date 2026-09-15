#!/bin/bash

pip3 install numpy==2.1.3 -q

# Ensure the input dataset exists (restore from backup if /app was cleared)
if [ ! -f /app/dataset.npy ]; then
    if [ -f /opt/dataset_backup.npy ]; then
        cp /opt/dataset_backup.npy /app/dataset.npy
    elif [ -f /opt/generate_data.py ]; then
        python3 /opt/generate_data.py
    fi
fi

cp /solution/lzw_float_writer.py /app/lzw_tiff_writer.py
cd /app
python3 /app/lzw_tiff_writer.py /app/dataset.npy /app/output.tif
