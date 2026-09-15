Three broken ONNX model files are in `/app/models/`: `normalize.onnx`, `transform.onnx`, and `classify.onnx`. Each model has multiple ONNX specification violations preventing validation with `onnx.checker.check_model(model, full_check=True)`. Some bugs are structural (caught by the checker), others are semantic (only detectable by comparing outputs to the specification).

Diagnose and fix all issues in each model. Then compose the three fixed models into a single sequential pipeline saved at `/app/pipeline.onnx`, flowing `normalize -> transform -> classify` with each model's output connected to the next model's input.

Define a model-local custom ONNX function called `SiLU` implementing `output = input * sigmoid(input)` using the `Sigmoid` and `Mul` operators. Replace the `Relu` activation in the transform stage with this `SiLU` function.

The final pipeline must:
- Pass `onnx.checker.check_model(pipeline, full_check=True)`
- Accept float32 input of shape `[N, 4]` and produce float32 output of shape `[N, 3]`
- Produce numerically correct results matching `/app/test_data/expected_output.npy` when given `/app/test_data/input.npy`
- Handle dynamic batch dimension N

The specification at `/app/spec.md` describes the intended computation and weight initialization parameters for each model component. The `onnx` and `numpy` packages are pre-installed.