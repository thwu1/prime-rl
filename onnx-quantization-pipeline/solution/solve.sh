#!/bin/bash

pip3 install onnx==1.16.0 onnxruntime==1.18.0 numpy==1.26.4 protobuf==5.27.2 -q

cd /app
python3 /app/generate_model.py
python3 /app/generate_calibration.py

cp /solution/quant_pipeline.py /app/quant_pipeline.py

python3 /app/quant_pipeline.py \
    --input /app/model.onnx \
    --calibration /app/calibration_data.npy \
    --config /app/config.json \
    --output-fused /app/model_fused.onnx \
    --output-quantized /app/model_quantized.onnx \
    --report /app/quantization_report.json
