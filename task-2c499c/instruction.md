`/app/pipeline.py` implements a YOLOv8n object-detection inference pipeline
using ONNX Runtime. It contains multiple bugs that cause it to produce
incorrect detections.

The environment provides:

- `/app/model.onnx` — YOLOv8n exported with 640x640 input
- `/app/images/` — test images of varying aspect ratios
- `/app/reference_detections.json` — correct detections from the PyTorch pipeline
- `/app/model_info.json` — model metadata (class names, thresholds, input size)

Fix `/app/pipeline.py` so that `python3 /app/pipeline.py` writes
`/app/detections.json` with results matching the reference. The pipeline must
use `onnxruntime` directly — do not use the `ultralytics` library at inference
time.

Your fixed pipeline must correctly handle images of different aspect ratios,
the YOLOv8-specific output tensor layout, and the coordinate mapping between
model input space and original image space.