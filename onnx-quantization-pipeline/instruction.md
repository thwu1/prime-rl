Scripts at `/app/generate_model.py` and `/app/generate_calibration.py` produce a seed ONNX model and calibration dataset. Run them to create `/app/model.onnx` and `/app/calibration_data.npy`. Quantization settings are in `/app/config.json`.

Create `/app/quant_pipeline.py` — a CLI tool that reads the ONNX model, calibration data, and configuration, then produces an optimized model, a quantized model, and a diagnostic report.

**CLI:**

```
python3 /app/quant_pipeline.py \
  --input /app/model.onnx \
  --calibration /app/calibration_data.npy \
  --config /app/config.json \
  --output-fused /app/model_fused.onnx \
  --output-quantized /app/model_quantized.onnx \
  --report /app/quantization_report.json
```

**Optimized model** (`model_fused.onnx`):
The model optimized according to the configuration. Must pass `onnx.checker.check_model`. Numerically equivalent to the original model (atol=1e-5 across multiple random inputs). Every Conv node must have a bias input. No unreferenced initializers may remain in the graph.

**Quantized model** (`model_quantized.onnx`):
A fake-quantized version of the optimized model, applying the quantization settings from the config. The calibration dataset must be used for activation range estimation. Must pass `onnx.checker.check_model`. Runnable via ONNX Runtime with input shape `[1, 3, 32, 32]` producing output shape `[1, 10]` with finite values. Quantization error relative to the optimized model must be bounded.

**Diagnostic report** (`quantization_report.json`):
JSON object with these keys:

- `"original_op_counts"`: `{op_type: count}` for every node type in the original model
- `"fused_op_counts"`: same for the optimized model
- `"num_quantized_weights"`: integer count of quantized weight tensors
- `"num_quantized_activations"`: integer count of quantized activation tensors
- `"weight_scale_ranges"`: `{conv_name: {"min": float, "max": float}}` — min and max of per-Conv weight quantization scales
- `"activation_scales"`: `{tensor_name: float}` — computed scale value per quantized activation tensor
