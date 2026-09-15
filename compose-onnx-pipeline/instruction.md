Three ONNX sub-models at `/app/models/` — `preprocess.onnx`, `encoder.onnx`, and `classifier.onnx` — implement stages of a data processing pipeline. They were exported by different teams using different ONNX opset versions and tensor configurations, and contain multiple cross-model incompatibilities that prevent naive concatenation.

Compose these three models into a single valid end-to-end ONNX model saved at `/app/pipeline.onnx`. The composed pipeline must satisfy **all** of the following requirements:

- Chain the models in order: preprocess -> encoder -> classifier
- Use exactly one opset import for the default ONNX domain (`""` or `"ai.onnx"`) with version >= 17
- Accept a single float32 input named `raw_input` with shape `[1, 1, 4]`
- Produce a single float32 output named `prediction` with shape `[1, 2]`
- The model must pass `onnx.checker.check_model(model, full_check=True)` with no errors
- The pipeline must produce numerically correct results when run with `onnxruntime`, equivalent to running the three sub-models in sequence with correct data flow between stages

Examine each sub-model's graph structure, operator definitions, tensor types, and internal naming to identify and resolve all incompatibilities. The `onnx` and `numpy` libraries are pre-installed.