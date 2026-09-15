Complete the GLM-5 Multi-Latent Attention module and build its deployment pipeline. The final state requires three working components:

The `MLAttention` class in `/app/mla_attention.py` must implement the full MLA forward pass per its docstring, integrate with the `SimpleGLM5` wrapper in `/app/model.py`, support KV caching for autoregressive decoding, and produce numerically stable differentiable outputs.

The C source at `/app/csrc/rope_fused.c` must implement fused RoPE matching the PyTorch implementation in `/app/utils.py`. The `/app/Makefile` must be fixed so that `make -C /app build` compiles the extension into a shared library at `/app/lib/librope.so` whose `rope_apply` and `rope_apply_batch` symbols are loadable via Python `ctypes`.

Running `python3 /app/export_onnx.py` must produce `/app/model.onnx` (valid per `onnx.checker`, with dynamic batch and sequence axes, inference matching PyTorch within 1e-4 via `onnxruntime`) and save model weights to `/app/model_weights.pt`.

Reference files: `/app/glm5_config.py`, `/app/utils.py`, `/app/model.py`.