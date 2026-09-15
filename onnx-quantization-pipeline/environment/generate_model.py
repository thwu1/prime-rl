#!/usr/bin/env python3
"""Generate a seed ONNX ConvNet model for the quantization pipeline task.

Architecture:
  Block 1: Conv(3->16, 3x3, pad=1, NO bias) -> BN(16) -> ReLU
  Block 2: Conv(16->32, 3x3, pad=1, WITH bias) -> BN(32) -> ReLU
  Block 3: Conv(32->10, 1x1, WITH bias) -> GlobalAveragePool -> Flatten

The first Conv deliberately omits bias to test the BN fusion edge case
where a bias must be created during folding.
"""

import numpy as np
import onnx
from onnx import helper, TensorProto



def create_initializer(name, array, dtype=TensorProto.FLOAT):
    return helper.make_tensor(
        name=name, data_type=dtype,
        dims=array.shape, vals=array.flatten().tolist())


def main():
    np.random.seed(42)

    # Graph I/O
    X = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 32, 32])
    Y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 10])

    initializers = []
    nodes = []

    # ---- Block 1: Conv1 (NO bias) + BN1 + ReLU1 ----
    conv1_w = np.random.randn(16, 3, 3, 3).astype(np.float32) * 0.1
    bn1_scale = (np.abs(np.random.randn(16)) + 0.5).astype(np.float32)
    bn1_bias = (np.random.randn(16) * 0.1).astype(np.float32)
    bn1_mean = (np.random.randn(16) * 0.5).astype(np.float32)
    bn1_var = (np.abs(np.random.randn(16)) + 0.1).astype(np.float32)

    initializers.extend([
        create_initializer("conv1_w", conv1_w),
        create_initializer("bn1_scale", bn1_scale),
        create_initializer("bn1_bias", bn1_bias),
        create_initializer("bn1_mean", bn1_mean),
        create_initializer("bn1_var", bn1_var),
    ])

    # Conv1 has only 2 inputs (no bias)
    nodes.append(helper.make_node(
        "Conv", ["input", "conv1_w"], ["conv1_out"],
        name="Conv1", kernel_shape=[3, 3], pads=[1, 1, 1, 1]))
    nodes.append(helper.make_node(
        "BatchNormalization",
        ["conv1_out", "bn1_scale", "bn1_bias", "bn1_mean", "bn1_var"],
        ["bn1_out"], name="BN1", epsilon=1e-5))
    nodes.append(helper.make_node(
        "Relu", ["bn1_out"], ["relu1_out"], name="Relu1"))

    # ---- Block 2: Conv2 (WITH bias) + BN2 + ReLU2 ----
    conv2_w = np.random.randn(32, 16, 3, 3).astype(np.float32) * 0.1
    conv2_b = np.random.randn(32).astype(np.float32) * 0.01
    bn2_scale = (np.abs(np.random.randn(32)) + 0.5).astype(np.float32)
    bn2_bias = (np.random.randn(32) * 0.1).astype(np.float32)
    bn2_mean = (np.random.randn(32) * 0.5).astype(np.float32)
    bn2_var = (np.abs(np.random.randn(32)) + 0.1).astype(np.float32)

    initializers.extend([
        create_initializer("conv2_w", conv2_w),
        create_initializer("conv2_b", conv2_b),
        create_initializer("bn2_scale", bn2_scale),
        create_initializer("bn2_bias", bn2_bias),
        create_initializer("bn2_mean", bn2_mean),
        create_initializer("bn2_var", bn2_var),
    ])

    nodes.append(helper.make_node(
        "Conv", ["relu1_out", "conv2_w", "conv2_b"], ["conv2_out"],
        name="Conv2", kernel_shape=[3, 3], pads=[1, 1, 1, 1]))
    nodes.append(helper.make_node(
        "BatchNormalization",
        ["conv2_out", "bn2_scale", "bn2_bias", "bn2_mean", "bn2_var"],
        ["bn2_out"], name="BN2", epsilon=1e-5))
    nodes.append(helper.make_node(
        "Relu", ["bn2_out"], ["relu2_out"], name="Relu2"))

    # ---- Block 3: Conv3 (pointwise, no BN) + GAP + Flatten ----
    conv3_w = np.random.randn(10, 32, 1, 1).astype(np.float32) * 0.1
    conv3_b = np.random.randn(10).astype(np.float32) * 0.01

    initializers.extend([
        create_initializer("conv3_w", conv3_w),
        create_initializer("conv3_b", conv3_b),
    ])

    nodes.append(helper.make_node(
        "Conv", ["relu2_out", "conv3_w", "conv3_b"], ["conv3_out"],
        name="Conv3", kernel_shape=[1, 1], pads=[0, 0, 0, 0]))
    nodes.append(helper.make_node(
        "GlobalAveragePool", ["conv3_out"], ["gap_out"], name="GAP"))
    nodes.append(helper.make_node(
        "Flatten", ["gap_out"], ["output"], name="Flatten", axis=1))

    # Build model
    graph = helper.make_graph(nodes, "ConvNet", [X], [Y], initializers)
    model = helper.make_model(graph, producer_name="task-generator")
    model.opset_import[0].version = 13

    model = onnx.shape_inference.infer_shapes(model)
    onnx.checker.check_model(model)
    onnx.save(model, "/app/model.onnx")
    print("Model saved to /app/model.onnx")


if __name__ == "__main__":
    main()
