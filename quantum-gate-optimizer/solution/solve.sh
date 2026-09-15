#!/usr/bin/env bash

pip3 install numpy==2.1.3 -q

cp /solution/optimizer_impl.py /app/optimizer.py
cp /solution/qasm_io_impl.py /app/qasm_io.py
cp /solution/pipeline_impl.py /app/run_pipeline.py
chmod +x /app/run_pipeline.py

cd /app && make benchmark
