#!/usr/bin/env python3

"""Compose three ONNX sub-models into a single pipeline.

Resolves: opset version mismatch, Squeeze attribute->input conversion,
tensor type mismatches (float32/float16), name collisions, I/O renaming.
"""
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper, version_converter


def prefix_names(model, prefix):
    """Add prefix to all names in a model's graph to avoid collisions."""
    graph = model.graph
    name_map = {}

    # Collect names from graph inputs, outputs
    for entry in list(graph.input) + list(graph.output):
        if entry.name:
            name_map[entry.name] = prefix + entry.name

    # Collect names from node outputs (these define edges)
    for node in graph.node:
        for o in node.output:
            if o and o not in name_map:
                name_map[o] = prefix + o

    # Collect initializer names
    for init in graph.initializer:
        if init.name and init.name not in name_map:
            name_map[init.name] = prefix + init.name

    # Collect value_info names
    for vi in graph.value_info:
        if vi.name and vi.name not in name_map:
            name_map[vi.name] = prefix + vi.name

    # Apply renaming to all node inputs/outputs
    for node in graph.node:
        for i in range(len(node.input)):
            if node.input[i] in name_map:
                node.input[i] = name_map[node.input[i]]
        for i in range(len(node.output)):
            if node.output[i] in name_map:
                node.output[i] = name_map[node.output[i]]
        # Handle subgraph attributes (If, Loop, etc.)
        for attr in node.attribute:
            if attr.type == onnx.AttributeProto.GRAPH:
                _prefix_subgraph(attr.g, name_map, prefix)

    # Apply to graph-level structures
    for entry in graph.input:
        if entry.name in name_map:
            entry.name = name_map[entry.name]
    for entry in graph.output:
        if entry.name in name_map:
            entry.name = name_map[entry.name]
    for init in graph.initializer:
        if init.name in name_map:
            init.name = name_map[init.name]
    for vi in graph.value_info:
        if vi.name in name_map:
            vi.name = name_map[vi.name]


def _prefix_subgraph(graph, name_map, prefix):
    """Apply existing name_map to a subgraph and prefix new names."""
    for node in graph.node:
        for i in range(len(node.input)):
            if node.input[i] in name_map:
                node.input[i] = name_map[node.input[i]]
        for i in range(len(node.output)):
            if node.output[i] in name_map:
                node.output[i] = name_map[node.output[i]]


def main():
    # Load sub-models
    preprocess = onnx.load("/app/models/preprocess.onnx")
    encoder = onnx.load("/app/models/encoder.onnx")
    classifier = onnx.load("/app/models/classifier.onnx")

    # Step 1: Harmonize opset versions
    # Convert preprocess from opset 11 to 17.
    # This automatically converts Squeeze axes from attribute to input tensor.
    preprocess = version_converter.convert_version(preprocess, 17)

    # Convert classifier from opset 13 to 17.
    classifier = version_converter.convert_version(classifier, 17)

    # encoder is already opset 17 — no conversion needed.

    # Step 2: Prefix internal names to avoid collisions.
    # Both preprocess and encoder use 'tmp' (edge) and 'scale' (initializer).
    prefix_names(preprocess, "pre_")
    prefix_names(encoder, "enc_")
    prefix_names(classifier, "cls_")

    # Step 3: Build the composed graph
    all_nodes = []
    all_initializers = []

    # Add preprocess nodes and initializers
    all_nodes.extend(preprocess.graph.node)
    all_initializers.extend(preprocess.graph.initializer)

    # Insert Cast: float32 -> float16 (preprocess output -> encoder input)
    cast_to_fp16 = helper.make_node(
        "Cast",
        ["pre_preprocess_output"],
        ["cast_to_fp16"],
        to=TensorProto.FLOAT16,
    )
    all_nodes.append(cast_to_fp16)

    # Rewire encoder input and add its nodes
    for node in encoder.graph.node:
        for i in range(len(node.input)):
            if node.input[i] == "enc_encoder_input":
                node.input[i] = "cast_to_fp16"
    all_nodes.extend(encoder.graph.node)
    all_initializers.extend(encoder.graph.initializer)

    # Insert Cast: float16 -> float32 (encoder output -> classifier input)
    cast_to_fp32 = helper.make_node(
        "Cast",
        ["enc_encoder_output"],
        ["cast_to_fp32"],
        to=TensorProto.FLOAT,
    )
    all_nodes.append(cast_to_fp32)

    # Rewire classifier input and add its nodes
    for node in classifier.graph.node:
        for i in range(len(node.input)):
            if node.input[i] == "cls_cls_input":
                node.input[i] = "cast_to_fp32"
    all_nodes.extend(classifier.graph.node)
    all_initializers.extend(classifier.graph.initializer)

    # Step 4: Rename external I/O
    # Rename pre_raw_input -> raw_input (pipeline input)
    for node in all_nodes:
        for i in range(len(node.input)):
            if node.input[i] == "pre_raw_input":
                node.input[i] = "raw_input"

    # Rename cls_cls_output -> prediction (pipeline output)
    for node in all_nodes:
        for i in range(len(node.output)):
            if node.output[i] == "cls_cls_output":
                node.output[i] = "prediction"

    # Step 5: Assemble the final model
    pipeline_input = helper.make_tensor_value_info(
        "raw_input", TensorProto.FLOAT, [1, 1, 4]
    )
    pipeline_output = helper.make_tensor_value_info(
        "prediction", TensorProto.FLOAT, [1, 2]
    )

    graph = helper.make_graph(
        all_nodes,
        "pipeline",
        [pipeline_input],
        [pipeline_output],
        initializer=all_initializers,
    )

    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)]
    )
    model.ir_version = 8

    # Validate
    onnx.checker.check_model(model, full_check=True)

    # Save
    onnx.save(model, "/app/pipeline.onnx")
    print("Pipeline saved to /app/pipeline.onnx")


if __name__ == "__main__":
    main()
