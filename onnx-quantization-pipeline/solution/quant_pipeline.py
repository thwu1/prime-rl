#!/usr/bin/env python3
"""ONNX Quantization Pipeline: Conv+BN Fusion, INT8 Q/DQ Insertion, Report.

Performs ONNX graph surgery to produce a BN-fused model and a
fake-quantized Q/DQ model, plus a diagnostic JSON report.
"""

import argparse
import copy
import json
import sys

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
import onnxruntime as ort



# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def get_initializer(graph, name):
    """Return initializer as numpy array, or None if not found."""
    for init in graph.initializer:
        if init.name == name:
            return numpy_helper.to_array(init)
    return None


def set_initializer(graph, name, array):
    """Replace an existing initializer or add a new one."""
    for i, init in enumerate(graph.initializer):
        if init.name == name:
            graph.initializer[i].CopyFrom(numpy_helper.from_array(array, name))
            return
    graph.initializer.append(numpy_helper.from_array(array, name))


def remove_initializer(graph, name):
    """Remove an initializer by name (no-op if not found)."""
    for i, init in enumerate(graph.initializer):
        if init.name == name:
            graph.initializer.pop(i)
            return


def count_ops(model):
    """Count node types in a model, returning {op_type: count}."""
    counts = {}
    for node in model.graph.node:
        counts[node.op_type] = counts.get(node.op_type, 0) + 1
    return counts


def get_node_by_output(graph, output_name, op_type):
    """Find a node of given op_type that produces output_name."""
    for n in graph.node:
        if n.op_type == op_type and output_name in n.output:
            return n
    return None


# ---------------------------------------------------------------------------
# Stage 1: Conv + BatchNormalization fusion
# ---------------------------------------------------------------------------

def fuse_conv_bn(model):
    """Fold every Conv+BN pair into a single Conv with fused weights/bias."""
    graph = model.graph
    nodes_to_remove = []

    for node in list(graph.node):
        if node.op_type != "BatchNormalization":
            continue

        bn_input_name = node.input[0]

        # Find the Conv that feeds this BN
        conv_node = None
        for n in graph.node:
            if n.op_type == "Conv" and bn_input_name in n.output:
                conv_node = n
                break
        if conv_node is None:
            continue

        # Only fuse when the Conv output is consumed exclusively by this BN
        consumer_count = sum(
            1 for n in graph.node for inp in n.input if inp == bn_input_name)
        if consumer_count != 1:
            continue

        # ---- Gather parameters ----
        conv_w = get_initializer(graph, conv_node.input[1])
        has_bias = (len(conv_node.input) >= 3 and conv_node.input[2] != "")
        conv_b = (get_initializer(graph, conv_node.input[2]) if has_bias
                  else np.zeros(conv_w.shape[0], dtype=np.float32))

        gamma = get_initializer(graph, node.input[1])
        beta = get_initializer(graph, node.input[2])
        mean = get_initializer(graph, node.input[3])
        var = get_initializer(graph, node.input[4])

        epsilon = 1e-5
        for attr in node.attribute:
            if attr.name == "epsilon":
                epsilon = attr.f

        # ---- Fuse ----
        std = np.sqrt(var + epsilon)
        scale_factor = gamma / std  # shape: (C_out,)

        fused_w = conv_w * scale_factor.reshape(-1, 1, 1, 1)
        fused_b = gamma * (conv_b - mean) / std + beta

        # ---- Update graph ----
        set_initializer(graph, conv_node.input[1], fused_w)

        if has_bias:
            set_initializer(graph, conv_node.input[2], fused_b)
        else:
            bias_name = conv_node.name + "_fused_bias"
            set_initializer(graph, bias_name, fused_b)
            conv_node.input.append(bias_name)

        # Redirect Conv output to BN's output tensor name
        conv_node.output[0] = node.output[0]

        nodes_to_remove.append(node)

        # Clean up BN-only initializers
        for inp_name in node.input[1:]:
            remove_initializer(graph, inp_name)

    # Remove BN nodes from graph
    for node in nodes_to_remove:
        graph.node.remove(node)

    # Remove stale intermediate value_info entries
    stale_names = {n.input[0] for n in nodes_to_remove}
    for vi in [v for v in graph.value_info if v.name in stale_names]:
        graph.value_info.remove(vi)

    model = onnx.shape_inference.infer_shapes(model)
    onnx.checker.check_model(model)
    return model


# ---------------------------------------------------------------------------
# Stage 2: Q/DQ insertion
# ---------------------------------------------------------------------------

def compute_per_channel_scales(weights, bits=8):
    """Symmetric per-channel scales: max(|W_c|) / (2^(bits-1) - 1)."""
    qmax = (1 << (bits - 1)) - 1  # 127 for 8-bit
    scales = np.empty(weights.shape[0], dtype=np.float32)
    for c in range(weights.shape[0]):
        ch_max = float(np.max(np.abs(weights[c])))
        scales[c] = ch_max / qmax if ch_max > 0 else 1.0
    return scales


def compute_activation_scales(model, calibration_data):
    """Compute per-tensor activation scales at each Conv's input location.

    For graph-level inputs the range is computed directly from calibration
    data.  For intermediate tensors, the fused model is temporarily modified
    to expose them as additional outputs so ONNX Runtime can capture the
    activation values during calibration.
    """
    graph_input_names = {inp.name for inp in model.graph.input}

    # Collect the activation tensor name for every Conv, preserving order
    conv_act_names = []
    for node in model.graph.node:
        if node.op_type == "Conv":
            conv_act_names.append(node.input[0])

    scales = {}

    # Graph inputs — range from raw calibration data
    for name in conv_act_names:
        if name in graph_input_names and name not in scales:
            max_val = float(np.max(np.abs(calibration_data)))
            scales[name] = max_val / 127.0 if max_val > 0 else 1.0

    # Intermediate tensors — need inference
    intermediates = list(dict.fromkeys(
        n for n in conv_act_names if n not in scales))

    if intermediates:
        model_copy = copy.deepcopy(model)
        for name in intermediates:
            vi = next((v for v in model_copy.graph.value_info
                       if v.name == name), None)
            if vi is not None:
                new_vi = onnx.ValueInfoProto()
                new_vi.CopyFrom(vi)
                model_copy.graph.output.append(new_vi)
            else:
                model_copy.graph.output.append(
                    helper.make_tensor_value_info(name, TensorProto.FLOAT, None))

        sess = ort.InferenceSession(model_copy.SerializeToString())
        input_name = sess.get_inputs()[0].name
        output_names = [o.name for o in sess.get_outputs()]

        max_vals = {n: 0.0 for n in intermediates}
        for i in range(calibration_data.shape[0]):
            sample = calibration_data[i]
            outputs = sess.run(output_names, {input_name: sample})
            for j, oname in enumerate(output_names):
                if oname in max_vals:
                    val = float(np.max(np.abs(outputs[j])))
                    if val > max_vals[oname]:
                        max_vals[oname] = val

        for name in intermediates:
            scales[name] = (max_vals[name] / 127.0
                            if max_vals[name] > 0 else 1.0)

    return scales


def insert_qdq_nodes(model, act_scales):
    """Insert QuantizeLinear/DequantizeLinear pairs around every Conv."""
    graph = model.graph

    new_nodes = []          # rebuilt node list
    new_initializers = []   # Q/DQ scale & zero-point tensors

    for node in list(graph.node):
        if node.op_type == "Conv":
            conv_name = node.name or f"conv_{id(node)}"

            # ---- Activation Q/DQ (per-tensor symmetric INT8) ----
            act_name = node.input[0]
            act_s = act_scales[act_name]

            act_s_name = f"{conv_name}_act_scale"
            act_z_name = f"{conv_name}_act_zp"
            act_q_out = f"{act_name}_q_{conv_name}"
            act_dq_out = f"{act_name}_dq_{conv_name}"

            new_initializers.append(numpy_helper.from_array(
                np.array(act_s, dtype=np.float32), act_s_name))
            new_initializers.append(numpy_helper.from_array(
                np.array(0, dtype=np.int8), act_z_name))

            new_nodes.append(helper.make_node(
                "QuantizeLinear",
                [act_name, act_s_name, act_z_name],
                [act_q_out],
                name=f"{conv_name}_act_Q"))
            new_nodes.append(helper.make_node(
                "DequantizeLinear",
                [act_q_out, act_s_name, act_z_name],
                [act_dq_out],
                name=f"{conv_name}_act_DQ"))

            node.input[0] = act_dq_out

            # ---- Weight Q/DQ (per-channel symmetric INT8, axis=0) ----
            w_name = node.input[1]
            weights = get_initializer(graph, w_name)
            w_scales = compute_per_channel_scales(weights)
            w_zps = np.zeros(weights.shape[0], dtype=np.int8)

            w_s_name = f"{conv_name}_w_scale"
            w_z_name = f"{conv_name}_w_zp"
            w_q_out = f"{w_name}_q_{conv_name}"
            w_dq_out = f"{w_name}_dq_{conv_name}"

            new_initializers.append(numpy_helper.from_array(w_scales, w_s_name))
            new_initializers.append(numpy_helper.from_array(w_zps, w_z_name))

            new_nodes.append(helper.make_node(
                "QuantizeLinear",
                [w_name, w_s_name, w_z_name],
                [w_q_out],
                name=f"{conv_name}_w_Q",
                axis=0))
            new_nodes.append(helper.make_node(
                "DequantizeLinear",
                [w_q_out, w_s_name, w_z_name],
                [w_dq_out],
                name=f"{conv_name}_w_DQ",
                axis=0))

            node.input[1] = w_dq_out

        new_nodes.append(node)

    # Rebuild the graph's node list in the new topological order
    while len(graph.node) > 0:
        graph.node.pop()
    for n in new_nodes:
        graph.node.append(n)

    for init in new_initializers:
        graph.initializer.append(init)

    # Ensure opset supports per-axis Q/DQ (>= 13)
    model.opset_import[0].version = max(model.opset_import[0].version, 13)

    model = onnx.shape_inference.infer_shapes(model)
    onnx.checker.check_model(model)
    return model


# ---------------------------------------------------------------------------
# Diagnostic report generation
# ---------------------------------------------------------------------------

def generate_report(original_model, fused_model, quantized_model,
                    act_scales, report_path):
    """Generate a JSON diagnostic report about the pipeline run."""
    graph = quantized_model.graph

    # Weight scale ranges per Conv
    weight_scale_ranges = {}
    for node in graph.node:
        if node.op_type == "Conv":
            conv_name = node.name or f"conv_{id(node)}"
            weight_input = node.input[1]
            dq = get_node_by_output(graph, weight_input, "DequantizeLinear")
            if dq is None:
                continue
            q = get_node_by_output(graph, dq.input[0], "QuantizeLinear")
            if q is None:
                continue
            scale_init = next((i for i in graph.initializer
                               if i.name == q.input[1]), None)
            if scale_init is not None:
                scale = numpy_helper.to_array(scale_init)
                weight_scale_ranges[conv_name] = {
                    "min": float(np.min(scale)),
                    "max": float(np.max(scale))
                }

    num_qw = sum(1 for n in graph.node if n.op_type == "Conv")
    num_qa = sum(1 for n in graph.node if n.op_type == "Conv")

    report = {
        "original_op_counts": count_ops(original_model),
        "fused_op_counts": count_ops(fused_model),
        "num_quantized_weights": num_qw,
        "num_quantized_activations": num_qa,
        "weight_scale_ranges": weight_scale_ranges,
        "activation_scales": {k: float(v) for k, v in act_scales.items()}
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved to {report_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ONNX Quantization Pipeline: BN fusion + Q/DQ insertion")
    parser.add_argument("--input", required=True, help="Input ONNX model")
    parser.add_argument("--calibration", required=True,
                        help="Calibration data (.npy)")
    parser.add_argument("--config", required=True, help="Config JSON")
    parser.add_argument("--output-fused", required=True,
                        help="Output path for BN-fused model")
    parser.add_argument("--output-quantized", required=True,
                        help="Output path for Q/DQ quantized model")
    parser.add_argument("--report", required=True,
                        help="Output path for diagnostic JSON report")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    # Load & validate original
    original_model = onnx.load(args.input)
    onnx.checker.check_model(original_model)

    # Stage 1: fuse Conv+BN
    model = copy.deepcopy(original_model)
    if config.get("quantization", {}).get("fuse_bn", True):
        model = fuse_conv_bn(model)
    onnx.save(model, args.output_fused)
    print(f"Fused model saved to {args.output_fused}")

    fused_model_for_report = copy.deepcopy(model)

    # Stage 2: compute activation scales and insert Q/DQ nodes
    calibration_data = np.load(args.calibration)
    act_scales = compute_activation_scales(model, calibration_data)
    model = insert_qdq_nodes(model, act_scales)
    onnx.save(model, args.output_quantized)
    print(f"Quantized model saved to {args.output_quantized}")

    # Stage 3: diagnostic report
    generate_report(original_model, fused_model_for_report, model,
                    act_scales, args.report)


if __name__ == "__main__":
    main()
