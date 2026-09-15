#!/usr/bin/env python3
"""
Write the complete ONNX export script for the GLM-5 MLA model.

"""

export_script = '''"""
Export the GLM-5 MLA model to ONNX format.

"""

import sys
sys.path.insert(0, "/app")

import torch
import torch.nn as nn

from glm5_config import GLM5Config
from model import SimpleGLM5


class ONNXWrapper(nn.Module):
    """Wraps SimpleGLM5 to return only logits for ONNX export."""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids):
        _, logits, _ = self.model(input_ids)
        return logits


def export_to_onnx(output_path="/app/model.onnx"):
    config = GLM5Config()
    torch.manual_seed(42)
    model = SimpleGLM5(config)
    model.eval()

    # Save weights for test verification
    torch.save(model.state_dict(), "/app/model_weights.pt")
    print("Model weights saved to /app/model_weights.pt")

    wrapper = ONNXWrapper(model)
    wrapper.eval()

    # Dummy input for tracing
    dummy_ids = torch.randint(0, config.vocab_size, (1, 8))

    torch.onnx.export(
        wrapper,
        (dummy_ids,),
        output_path,
        input_names=["input_ids"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "logits": {0: "batch", 1: "seq"},
        },
        opset_version=17,
        do_constant_folding=True,
    )
    print(f"ONNX model exported to {output_path}")

    # Validate
    import onnx
    model_onnx = onnx.load(output_path)
    onnx.checker.check_model(model_onnx)
    print("ONNX checker passed")


if __name__ == "__main__":
    export_to_onnx()
'''

with open("/app/export_onnx.py", "w") as f:
    f.write(export_script)

print("ONNX export script written to /app/export_onnx.py")
