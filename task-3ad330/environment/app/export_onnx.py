"""
Export the GLM-5 MLA model to ONNX format.

Usage: python3 /app/export_onnx.py

Must produce:
  /app/model.onnx       - Valid ONNX model (opset >= 17, dynamic batch/seq axes)
  /app/model_weights.pt - PyTorch state_dict for reproducible verification

Requirements:
  - input_names:  ["input_ids"]
  - output_names: ["logits"]
  - dynamic_axes for both batch_size (dim 0) and sequence_length (dim 1)
  - Must pass onnx.checker.check_model()
  - Inference via onnxruntime must match PyTorch within 1e-4

"""

import sys
sys.path.insert(0, "/app")

import torch
import torch.nn as nn

from glm5_config import GLM5Config
from model import SimpleGLM5


class ONNXWrapper(nn.Module):
    """Wraps SimpleGLM5 to return only logits (ONNX requires tensor outputs)."""

    def __init__(self, model: SimpleGLM5):
        super().__init__()
        self.model = model

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        # TODO: call self.model appropriately and return only the logits tensor
        raise NotImplementedError("Implement the wrapper forward method")


def export_to_onnx(output_path: str = "/app/model.onnx"):
    """Export the model to ONNX with dynamic axes for batch and sequence."""
    config = GLM5Config()
    torch.manual_seed(42)
    model = SimpleGLM5(config)
    model.eval()

    # TODO: save model state_dict to /app/model_weights.pt
    # TODO: create ONNXWrapper, build dummy input_ids, call torch.onnx.export
    raise NotImplementedError("Complete the ONNX export pipeline")


if __name__ == "__main__":
    export_to_onnx()
    print("ONNX export complete: /app/model.onnx")
