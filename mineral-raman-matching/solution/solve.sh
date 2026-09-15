#!/bin/bash


pip3 install numpy==1.26.4 -q

cp /solution/mineral_id_impl.py /app/mineral_id.py
cp /solution/pipeline_impl.sh /app/pipeline.sh
chmod +x /app/pipeline.sh
